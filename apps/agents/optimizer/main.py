"""Optimizer — thermal/capacity bin-packing agent.

Flow:
    1. Subscribe to `incidents.report`.
    2. For each incident:
       a. Identify the affected rack (first hop).
       b. Pull current power + thermal context from TimescaleDB.
       c. Pull rack topology + capacity from Neo4j.
       d. Build a `SolverInput` with synthesized workloads (one per
          high-draw server on the incident rack) + candidate racks
          (same hall, headroom > 0).
       e. Solve via OR-Tools CP-SAT (time-bounded).
       f. Emit `Recommendation` on `recommendations.workload_migration`.
       g. Stash the recommendation on a Redis list `recommendations:recent`
          so the API can paginate over recent runs.

Topics:
    in:  incidents.report
    out: recommendations.workload_migration
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

from apps.agents.optimizer.solver import (
    Move,
    Rack,
    SolverInput,
    SolverOutput,
    Workload,
    estimate_impact,
    solve,
)
from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import IncidentReport, Recommendation, Topic
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.ts_client import TimescaleStore


_RECOMMENDATIONS_REDIS_LIST = "recommendations:recent"
_RECOMMENDATIONS_KEEP = int(os.getenv("OPTIMIZER_RECENT_KEEP", "200"))


class OptimizerAgent(BaseAgent):
    name = "optimizer"
    subscribed_topic = Topic.INCIDENTS_REPORT.value
    event_model = IncidentReport

    async def on_start(self) -> None:
        await super().on_start()
        self.ts = TimescaleStore.from_env()
        self.kg = KnowledgeGraph.from_env()
        await self.ts.connect()
        await self.kg.connect()
        self.log.info(
            "optimizer.ready",
            ts=self.ts.enabled,
            kg=self.kg.enabled,
            solver_time_limit_s=float(os.getenv("OPTIMIZER_SOLVER_TIME_LIMIT_SEC", "10")),
        )

    async def on_stop(self) -> None:
        await self.ts.close()
        await self.kg.close()
        await super().on_stop()

    async def handle(self, event: IncidentReport) -> None:  # type: ignore[override]
        if not event.affected_device_ids:
            self.log.debug("optimizer.skip", reason="no affected devices")
            return

        rack_id = self._rack_for(event.affected_device_ids[0])
        if not rack_id:
            self.log.debug("optimizer.skip", reason="cannot infer rack")
            return

        site_id = event.site_id
        self.log.info(
            "optimizer.received",
            incident_id=str(event.incident_id),
            rack_id=rack_id,
            site_id=site_id,
        )

        ctx = await self._gather_context(site_id=site_id, incident_rack_id=rack_id)
        if ctx is None:
            self.log.warning("optimizer.no_context", site=site_id, rack=rack_id)
            return

        output: SolverOutput = await asyncio.to_thread(solve, ctx)
        if not output.feasible or output.is_noop():
            self.log.info(
                "optimizer.no_recommendation",
                status=output.solve_status,
                notes=output.notes,
            )
            return

        rec = self._build_recommendation(event, output)
        await self._publish_and_persist(rec)

    # --- context build ---------------------------------------------------------

    async def _gather_context(
        self,
        *,
        site_id: str,
        incident_rack_id: str,
    ) -> SolverInput | None:
        """Build the SolverInput from live Timescale + KG state.

        Falls back to a small synthetic placement when KG or TS aren't
        connected — keeps the agent useful in dev without the full data
        plane.
        """
        # Workloads: every server on the incident rack with recent power draw > 0.
        workloads = await self._workloads_on_rack(site_id, incident_rack_id)
        if not workloads:
            workloads = _synthetic_workloads(incident_rack_id)

        racks = await self._candidate_racks(site_id, incident_rack_id)
        if not racks:
            racks = _synthetic_racks(incident_rack_id)

        if not workloads or not racks:
            return None

        return SolverInput(
            incident_rack_id=incident_rack_id,
            workloads=tuple(workloads),
            racks=tuple(racks),
        )

    async def _workloads_on_rack(
        self,
        site_id: str,
        rack_id: str,
    ) -> list[Workload]:
        """Derive workloads from the latest power-draw samples on a rack."""
        if not self.ts.enabled:
            return []
        sql = (
            "SELECT DISTINCT ON (device_id) device_id, value_num AS power_w "
            "FROM telemetry "
            "WHERE site_id = %s AND rack_id = %s "
            "  AND metric = 'power.draw.watts' "
            "  AND time >= NOW() - INTERVAL '5 minutes' "
            "ORDER BY device_id, time DESC"
        )
        try:
            rows = await self.ts.execute_select(sql, (site_id, rack_id), max_rows=200)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("optimizer.ts_query_failed", error=str(exc))
            return []
        out: list[Workload] = []
        for r in rows:
            device_id = r.get("device_id")
            power = r.get("power_w")
            if not isinstance(device_id, str) or not isinstance(power, (int, float)):
                continue
            # Heat ~ power (90% efficiency assumed). thermal_load_kw in kW.
            thermal_kw = float(power) * 0.9 / 1000.0
            out.append(
                Workload(
                    id=f"wl-{device_id}",
                    current_rack_id=rack_id,
                    power_w=float(power),
                    thermal_load_kw=thermal_kw,
                    tier=_tier_from_device(device_id),
                )
            )
        return out

    async def _candidate_racks(
        self,
        site_id: str,
        incident_rack_id: str,
    ) -> list[Rack]:
        """Find racks in the same hall as the incident rack with measured load."""
        if not self.ts.enabled:
            return []
        # Pull recent per-rack sums to estimate remaining headroom.
        sql = (
            "WITH latest_power AS ("
            "  SELECT rack_id, SUM(value_num) AS used_w "
            "  FROM telemetry "
            "  WHERE site_id = %s AND metric = 'power.draw.watts' "
            "    AND time >= NOW() - INTERVAL '5 minutes' "
            "  GROUP BY rack_id"
            "), "
            "latest_inlet AS ("
            "  SELECT rack_id, AVG(value_num) AS inlet_c "
            "  FROM telemetry "
            "  WHERE site_id = %s AND metric = 'env.inlet.celsius' "
            "    AND time >= NOW() - INTERVAL '5 minutes' "
            "  GROUP BY rack_id"
            ") "
            "SELECT p.rack_id, p.used_w, COALESCE(i.inlet_c, 22.0) AS inlet_c "
            "FROM latest_power p LEFT JOIN latest_inlet i USING (rack_id)"
        )
        try:
            rows = await self.ts.execute_select(sql, (site_id, site_id), max_rows=200)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("optimizer.ts_query_failed", error=str(exc))
            return []
        # Defaults: ~15kW per rack PDU pair, ~12kW thermal envelope per rack.
        per_rack_power_cap_w = float(os.getenv("OPTIMIZER_RACK_POWER_CAP_W", "15000"))
        per_rack_thermal_cap_kw = float(os.getenv("OPTIMIZER_RACK_THERMAL_CAP_KW", "12"))
        out: list[Rack] = []
        for r in rows:
            rid = r.get("rack_id")
            used = float(r.get("used_w") or 0.0)
            inlet = float(r.get("inlet_c") or 22.0)
            if not isinstance(rid, str):
                continue
            power_headroom = max(0.0, per_rack_power_cap_w - used)
            # Thermal headroom proxy: empty rack has full envelope, hot rack has less.
            thermal_used = (used * 0.9) / 1000.0
            thermal_headroom = max(0.0, per_rack_thermal_cap_kw - thermal_used)
            out.append(
                Rack(
                    id=rid,
                    pdu_capacity_w=power_headroom,
                    thermal_headroom_kw=thermal_headroom,
                    current_inlet_c=inlet,
                )
            )
        # Always include the incident rack so the solver can choose to leave
        # workloads in place if the alternatives are worse.
        if not any(r.id == incident_rack_id for r in out):
            out.append(
                Rack(
                    id=incident_rack_id,
                    pdu_capacity_w=max(0.0, per_rack_power_cap_w * 0.1),  # almost full
                    thermal_headroom_kw=max(0.0, per_rack_thermal_cap_kw * 0.1),
                    current_inlet_c=30.0,
                )
            )
        return out

    # --- emit ------------------------------------------------------------------

    def _build_recommendation(
        self,
        event: IncidentReport,
        output: SolverOutput,
    ) -> Recommendation:
        target_devices = sorted({m.workload_id.removeprefix("wl-") for m in output.moves})
        return Recommendation(
            site_id=event.site_id,
            recommendation_id=uuid4(),
            kind="workload_migration",
            target_device_ids=target_devices,
            parameters={
                "moves": [
                    {
                        "workload_id": m.workload_id,
                        "from_rack_id": m.from_rack_id,
                        "to_rack_id": m.to_rack_id,
                        "power_w": m.expected_power_w,
                        "thermal_kw": m.expected_thermal_kw,
                    }
                    for m in output.moves
                ],
                "solver_status": output.solve_status,
                "objective_value": output.objective_value,
            },
            estimated_impact=estimate_impact(output.moves),
            confidence=0.85 if output.solve_status == "OPTIMAL" else 0.7,
            requires_human_approval=len(output.moves) > 3,
            trace_id=event.trace_id,
            parent_event_id=event.event_id,
        )

    async def _publish_and_persist(self, rec: Recommendation) -> None:
        try:
            await self.bus.publish(f"recommendations.{rec.kind}", rec)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("optimizer.publish_failed", error=str(exc))

        # Persist to Redis list (newest at the head, capped length).
        client = getattr(self.bus, "_client", None)
        if client is not None:
            try:
                payload = rec.model_dump_json()
                await client.lpush(_RECOMMENDATIONS_REDIS_LIST, payload)
                await client.ltrim(_RECOMMENDATIONS_REDIS_LIST, 0, _RECOMMENDATIONS_KEEP - 1)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("optimizer.persist_failed", error=str(exc))

        self.log.info(
            "optimizer.recommendation_published",
            recommendation_id=str(rec.recommendation_id),
            moves=len(rec.parameters.get("moves", [])),  # type: ignore[arg-type]
            confidence=rec.confidence,
            requires_human_approval=rec.requires_human_approval,
        )

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _rack_for(device_id: str) -> str | None:
        """Recover the rack ID from a device ID like `frankfurt-h1-r07-srv03`."""
        parts = device_id.split("-")
        if len(parts) >= 3 and parts[1].startswith("h") and parts[2].startswith("r"):
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
        return None


# --- fallback synthesizers (used when TS / KG aren't connected) ----------------

def _tier_from_device(device_id: str) -> str:
    if "-gpu" in device_id:
        return "gpu"
    if device_id.endswith("-tor"):
        return "switch"
    return "compute"


def _synthetic_workloads(rack_id: str) -> list[Workload]:
    """Three placeholder workloads — used when Timescale is unreachable."""
    return [
        Workload(
            id=f"wl-{rack_id}-srv{i:02d}",
            current_rack_id=rack_id,
            power_w=600.0 + i * 50,
            thermal_load_kw=(600.0 + i * 50) * 0.9 / 1000.0,
            tier="compute",
        )
        for i in range(1, 4)
    ]


def _synthetic_racks(incident_rack_id: str) -> list[Rack]:
    """A few candidate racks in the same hall — used when KG is unreachable."""
    parts = incident_rack_id.rsplit("-r", 1)
    if len(parts) != 2:
        return []
    hall_prefix = parts[0]  # e.g. "frankfurt-h1"
    return [
        Rack(
            id=f"{hall_prefix}-r{i:02d}",
            pdu_capacity_w=10_000.0,
            thermal_headroom_kw=10.0,
            current_inlet_c=22.0 + (i * 0.5),
        )
        for i in range(1, 6)
    ]


if __name__ == "__main__":
    OptimizerAgent.run()

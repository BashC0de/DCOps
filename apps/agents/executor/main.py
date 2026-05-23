"""Action Executor — closed-loop remediation.

Flow per incoming `Recommendation`:
    1. Decide via the policy engine.
       - DENIED       → log, persist, drop.
       - NEEDS_HUMAN  → publish on `actions.needs_human` (dashboard surfaces it).
       - APPROVED     → continue.
    2. Snapshot pre-action KPIs (per recommendation kind) from Timescale.
    3. Resolve the action handler for `recommendation.kind`. If none, refuse.
    4. Call the handler (HTTP POST to mock vendor endpoint).
    5. Publish `ActionExecuted` on `actions.executed`.
    6. Persist the action to the Redis list `actions:recent`.

Topics:
    in:  recommendations.*
    out: actions.executed | actions.needs_human
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

from apps.agents.executor import actions
from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import ActionExecuted, Recommendation, Topic
from apps.agents.shared.ts_client import TimescaleStore
from apps.control_plane.policy_engine import Decision, PolicyEngine


_ACTIONS_LIST = "actions:recent"
_ACTIONS_KEEP = int(os.getenv("EXECUTOR_RECENT_KEEP", "500"))


class ExecutorAgent(BaseAgent):
    name = "executor"
    subscribed_topic = Topic.RECOMMENDATIONS_ALL.value
    event_model = None    # multiple kinds; parse from dict

    async def on_start(self) -> None:
        await super().on_start()
        self.ts = TimescaleStore.from_env()
        await self.ts.connect()
        self.policy = PolicyEngine.from_default_config()
        self.log.info(
            "executor.ready",
            n_policies=len(self.policy.policies),
            ts_enabled=self.ts.enabled,
            handlers=sorted(actions.HANDLERS.keys()),
        )

    async def on_stop(self) -> None:
        await self.ts.close()
        await super().on_stop()

    async def handle(self, event: Any) -> None:
        rec = self._parse(event)
        if rec is None:
            return

        decision, reason, applied = self.policy.evaluate(rec)
        self.log.info(
            "executor.policy_decision",
            recommendation_id=str(rec.recommendation_id),
            decision=decision.value,
            reason=reason,
            applied=applied,
        )

        if decision is Decision.DENIED:
            await self._record_denied(rec, reason or "")
            return

        if decision is Decision.NEEDS_HUMAN:
            await self._publish_needs_human(rec, reason or "")
            return

        await self._execute(rec)

    # --- approval paths --------------------------------------------------------

    async def _execute(self, rec: Recommendation) -> None:
        handler = actions.resolve(rec.kind)
        if handler is None:
            await self._record_denied(rec, f"no handler for kind {rec.kind!r}")
            return

        action_id = uuid4()
        pre_kpis = await self._snapshot_kpis(rec)
        ok, payload = await handler(rec, str(action_id))

        event = ActionExecuted(
            site_id=rec.site_id,
            recommendation_id=rec.recommendation_id,
            action_id=action_id,
            success=ok,
            response_payload=payload,
            pre_action_kpis=pre_kpis,
            trace_id=rec.trace_id,
            parent_event_id=rec.event_id,
            metadata={"kind": rec.kind, "agent": self.name},
        )
        try:
            await self.bus.publish(Topic.ACTIONS_EXECUTED.value, event)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("executor.publish_failed", error=str(exc))

        await self._persist_action(event)
        self.log.info(
            "executor.action_executed",
            recommendation_id=str(rec.recommendation_id),
            action_id=str(action_id),
            kind=rec.kind,
            success=ok,
        )

    async def _publish_needs_human(self, rec: Recommendation, reason: str) -> None:
        try:
            await self.bus.publish(
                "actions.needs_human",
                rec.model_copy(update={"metadata": {**rec.metadata, "policy_reason": reason}}),
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("executor.needs_human_publish_failed", error=str(exc))

    async def _record_denied(self, rec: Recommendation, reason: str) -> None:
        """Persist a denied recommendation as a non-successful ActionExecuted."""
        event = ActionExecuted(
            site_id=rec.site_id,
            recommendation_id=rec.recommendation_id,
            action_id=uuid4(),
            success=False,
            response_payload={"denied": True, "reason": reason},
            pre_action_kpis={},
            trace_id=rec.trace_id,
            parent_event_id=rec.event_id,
            metadata={"kind": rec.kind, "denied_reason": reason},
        )
        await self._persist_action(event)
        self.log.info(
            "executor.denied",
            recommendation_id=str(rec.recommendation_id),
            kind=rec.kind,
            reason=reason,
        )

    # --- helpers --------------------------------------------------------------

    async def _snapshot_kpis(self, rec: Recommendation) -> dict[str, float]:
        """Capture the KPIs the Rollback Monitor will compare against later."""
        if not self.ts.enabled or not rec.target_device_ids:
            return {}
        # KPIs depend on action kind. For now we cover the two common ones.
        metrics = _kpi_metrics_for(rec.kind)
        out: dict[str, float] = {}
        for metric in metrics:
            sql = (
                "SELECT AVG(value_num) AS v "
                "FROM telemetry "
                "WHERE site_id = %s AND metric = %s "
                "  AND device_id = ANY(%s::text[]) "
                "  AND time >= NOW() - INTERVAL '5 minutes'"
            )
            try:
                rows = await self.ts.execute_select(
                    sql,
                    (rec.site_id, metric, rec.target_device_ids),
                    max_rows=1,
                )
            except Exception as exc:  # noqa: BLE001
                self.log.debug("executor.kpi_snapshot_failed", metric=metric, error=str(exc))
                continue
            if rows:
                v = rows[0].get("v")
                if isinstance(v, (int, float)):
                    out[metric] = float(v)
        return out

    async def _persist_action(self, action: ActionExecuted) -> None:
        client = getattr(self.bus, "_client", None)
        if client is None:
            return
        try:
            payload = action.model_dump_json()
            await client.lpush(_ACTIONS_LIST, payload)
            await client.ltrim(_ACTIONS_LIST, 0, _ACTIONS_KEEP - 1)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("executor.persist_failed", error=str(exc))

    @staticmethod
    def _parse(event: Any) -> Recommendation | None:
        if isinstance(event, Recommendation):
            return event
        if isinstance(event, dict):
            try:
                return Recommendation.model_validate(event)
            except Exception:  # noqa: BLE001
                return None
        return None


# --- kind → KPI metric set -----------------------------------------------------


def _kpi_metrics_for(kind: str) -> tuple[str, ...]:
    return {
        "workload_migration": (
            "env.inlet.celsius",
            "env.outlet.celsius",
            "power.draw.watts",
            "cpu.temp.celsius",
        ),
        "fan_speed_adjust": (
            "cpu.temp.celsius",
            "fan.rpm",
        ),
    }.get(kind, ("env.inlet.celsius",))


if __name__ == "__main__":
    ExecutorAgent.run()

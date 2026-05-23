"""Rollback Monitor — post-action KPI verification.

For every `ActionExecuted`:
    1. Sleep for `ROLLBACK_OBSERVATION_S` (default 300s).
    2. Snapshot the same KPIs against Timescale.
    3. Compare pre vs post per metric:
         - Lower-is-better (`*.celsius`, `*.percent` for util, ECC, etc.):
             post > pre × (1 + threshold)  → regression
         - Higher-is-better (`fan.rpm`):
             post < pre × (1 - threshold)  → regression
    4. If ANY metric regresses past threshold, call the revert endpoint
       and publish `ActionRolledBack`.
    5. Otherwise log `rollback.committed`.

Topics:
    in:  actions.executed
    out: actions.rolled_back
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from apps.agents.executor import actions as executor_actions
from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import ActionExecuted, ActionRolledBack, Topic
from apps.agents.shared.ts_client import TimescaleStore


_OBSERVATION_S = float(os.getenv("ROLLBACK_OBSERVATION_S", "300"))
_REGRESSION_THRESHOLD = float(os.getenv("ROLLBACK_REGRESSION_THRESHOLD", "0.10"))  # 10%
# Metrics where smaller-is-better. Everything else (notably fan.rpm) gets the
# inverted comparison.
_LOWER_IS_BETTER = {
    "cpu.temp.celsius",
    "gpu.temp.celsius",
    "env.inlet.celsius",
    "env.outlet.celsius",
    "power.draw.watts",
    "psu.efficiency.percent",     # actually higher = better; corrected below
    "gpu.ecc.uncorrectable",
    "gpu.ecc.correctable",
    "disk.temp.celsius",
    "net.err.in",
    "pdu.load.percent",
}
_HIGHER_IS_BETTER = {
    "fan.rpm",
    "net.port.up",
    "psu.efficiency.percent",
}


def is_regression(metric: str, pre: float, post: float, *, threshold: float) -> bool:
    """True if `post` is materially worse than `pre` for `metric`."""
    if metric in _HIGHER_IS_BETTER:
        return post < pre * (1.0 - threshold)
    # Default: lower is better.
    return post > pre * (1.0 + threshold)


class RollbackAgent(BaseAgent):
    name = "rollback"
    subscribed_topic = Topic.ACTIONS_EXECUTED.value
    event_model = ActionExecuted

    async def on_start(self) -> None:
        await super().on_start()
        self.ts = TimescaleStore.from_env()
        await self.ts.connect()
        self._inflight: set[str] = set()
        self.log.info(
            "rollback.ready",
            observation_s=_OBSERVATION_S,
            threshold=_REGRESSION_THRESHOLD,
            ts_enabled=self.ts.enabled,
        )

    async def on_stop(self) -> None:
        await self.ts.close()
        await super().on_stop()

    async def handle(self, event: ActionExecuted) -> None:  # type: ignore[override]
        if not event.success:
            self.log.debug(
                "rollback.skip", reason="action did not execute successfully",
                action_id=str(event.action_id),
            )
            return
        if not event.pre_action_kpis:
            self.log.debug(
                "rollback.skip", reason="no pre-action KPIs to compare against",
                action_id=str(event.action_id),
            )
            return
        action_id_str = str(event.action_id)
        if action_id_str in self._inflight:
            return
        self._inflight.add(action_id_str)
        # Schedule the delayed verification — don't block the bus loop.
        asyncio.create_task(self._verify_later(event))

    # --- verification ----------------------------------------------------------

    async def _verify_later(self, event: ActionExecuted) -> None:
        try:
            await asyncio.sleep(_OBSERVATION_S)
            await self._verify(event)
        finally:
            self._inflight.discard(str(event.action_id))

    async def _verify(self, event: ActionExecuted) -> None:
        site_id = event.site_id
        post_kpis = await self._snapshot_post_kpis(event)
        regressions: dict[str, dict[str, float]] = {}
        for metric, pre_val in event.pre_action_kpis.items():
            post_val = post_kpis.get(metric)
            if post_val is None:
                continue
            if is_regression(metric, float(pre_val), float(post_val), threshold=_REGRESSION_THRESHOLD):
                regressions[metric] = {"pre": float(pre_val), "post": float(post_val)}

        if not regressions:
            self.log.info(
                "rollback.committed",
                action_id=str(event.action_id),
                site_id=site_id,
                pre_kpis=event.pre_action_kpis,
                post_kpis=post_kpis,
            )
            return

        await self._trigger_revert(event, post_kpis=post_kpis, regressions=regressions)

    async def _snapshot_post_kpis(self, event: ActionExecuted) -> dict[str, float]:
        """Snapshot the same metrics the Executor recorded pre-action."""
        # Without TS, we trust pre-KPIs (no post sample → no regression detected).
        if not self.ts.enabled:
            return {}
        out: dict[str, float] = {}
        # Devices to query come from the recommendation, not the executed event;
        # but the executed event carries `metadata.kind` and we can recover
        # device IDs from the response_payload moves (for migration kind) or
        # the recommendation_id if needed. For Week 8 we use the metrics list
        # alone and average across the site as a coarse proxy when the
        # response_payload doesn't carry device IDs.
        device_ids = _extract_devices(event)
        for metric in event.pre_action_kpis.keys():
            if device_ids:
                sql = (
                    "SELECT AVG(value_num) AS v "
                    "FROM telemetry "
                    "WHERE site_id = %s AND metric = %s "
                    "  AND device_id = ANY(%s::text[]) "
                    "  AND time >= NOW() - INTERVAL '5 minutes'"
                )
                params: tuple[Any, ...] = (event.site_id, metric, device_ids)
            else:
                sql = (
                    "SELECT AVG(value_num) AS v "
                    "FROM telemetry "
                    "WHERE site_id = %s AND metric = %s "
                    "  AND time >= NOW() - INTERVAL '5 minutes'"
                )
                params = (event.site_id, metric)
            try:
                rows = await self.ts.execute_select(sql, params, max_rows=1)
            except Exception as exc:  # noqa: BLE001
                self.log.debug("rollback.snapshot_failed", metric=metric, error=str(exc))
                continue
            if rows:
                v = rows[0].get("v")
                if isinstance(v, (int, float)):
                    out[metric] = float(v)
        return out

    async def _trigger_revert(
        self,
        event: ActionExecuted,
        *,
        post_kpis: dict[str, float],
        regressions: dict[str, dict[str, float]],
    ) -> None:
        reason = "; ".join(
            f"{m} pre={d['pre']:.2f} post={d['post']:.2f}"
            for m, d in regressions.items()
        )

        ok, response = await executor_actions.revert(
            original_action_id=str(event.action_id),
            reason=reason,
        )

        rolled = ActionRolledBack(
            site_id=event.site_id,
            action_id=event.action_id,
            reason=reason,
            pre_action_kpis=event.pre_action_kpis,
            post_action_kpis=post_kpis,
            trace_id=event.trace_id,
            parent_event_id=event.event_id,
            metadata={"revert_ok": ok, "revert_response": response},
        )
        try:
            await self.bus.publish(Topic.ACTIONS_ROLLED_BACK.value, rolled)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("rollback.publish_failed", error=str(exc))

        self.log.warning(
            "rollback.triggered",
            action_id=str(event.action_id),
            site_id=event.site_id,
            regressions=regressions,
            revert_ok=ok,
        )


def _extract_devices(event: ActionExecuted) -> list[str]:
    """Pull target device IDs from the executor's response payload, if any."""
    payload = event.response_payload or {}
    if isinstance(payload, dict):
        moves = payload.get("moves") or []
        if isinstance(moves, list):
            out: list[str] = []
            for m in moves:
                if isinstance(m, dict):
                    wl = m.get("workload_id")
                    if isinstance(wl, str):
                        # Workload IDs in the optimizer are `wl-<device_id>`.
                        out.append(wl.removeprefix("wl-"))
            if out:
                return out
        dev = payload.get("device_id")
        if isinstance(dev, str):
            return [dev]
    return []


__all__ = ["RollbackAgent", "is_regression"]


if __name__ == "__main__":
    RollbackAgent.run()

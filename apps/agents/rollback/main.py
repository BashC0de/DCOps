"""Rollback Monitor — post-action telemetry verification.

Purpose:
    Subscribes to `actions.executed`. For each action:
      1. Capture KPIs from a configurable post-action window
         (default: 5 minutes).
      2. Compare against `pre_action_kpis` carried on the event.
      3. If KPIs degrade beyond threshold, publish `ActionRolledBack` and
         instruct the Executor to revert.

Ships: Week 8 (see ROADMAP.md).

Topics:
    in:  actions.executed
    out: actions.rolled_back
"""

from __future__ import annotations

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import ActionExecuted, Topic


class RollbackAgent(BaseAgent):
    name = "rollback"
    subscribed_topic = Topic.ACTIONS_EXECUTED.value
    event_model = ActionExecuted

    async def on_start(self) -> None:
        await super().on_start()
        # TODO(week-8): connect TimescaleDB read client; load KPI thresholds
        #               per action kind from config.
        self.log.info("rollback.ready", note="skeleton — verifier ships Week 8")

    async def handle(self, event: ActionExecuted) -> None:  # type: ignore[override]
        self.log.info("rollback.observing", action_id=str(event.action_id))
        # TODO(week-8): schedule a delayed task to pull post-action KPIs, compare,
        #               and emit ActionRolledBack if degradation crosses threshold.


if __name__ == "__main__":
    RollbackAgent.run()

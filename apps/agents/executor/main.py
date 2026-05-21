"""Action Executor — closed-loop remediation.

Purpose:
    Subscribes to `recommendations.*`. For each:
      1. Validate audit lineage exists.
      2. Submit to the central policy engine (gRPC).
      3. If approved, call the (mocked) remediation endpoint for that action kind.
      4. Capture pre-action KPIs; publish `ActionExecuted` on `actions.executed`.

Ships: Week 8 (see ROADMAP.md).

Action mocks live in `apps/agents/executor/actions.py` (added Week 8).

Topics:
    in:  recommendations.*
    out: actions.executed
"""

from __future__ import annotations

from typing import Any

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import Topic


class ExecutorAgent(BaseAgent):
    name = "executor"
    subscribed_topic = Topic.RECOMMENDATIONS_ALL.value
    event_model = None                    # parsed by recommendation kind, not statically

    async def on_start(self) -> None:
        await super().on_start()
        # TODO(week-8): connect gRPC client to control-plane policy engine;
        #               load action-kind → handler registry.
        self.log.info("executor.ready", note="skeleton — closed-loop ships Week 8")

    async def handle(self, event: Any) -> None:
        # TODO(week-8): policy check → execute mocked action → record KPIs → publish ActionExecuted.
        self.log.debug("executor.tick", payload_keys=list(event.keys()) if isinstance(event, dict) else None)


if __name__ == "__main__":
    ExecutorAgent.run()

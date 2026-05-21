"""Forensic — automated RCA agent.

Purpose:
    Triggered by `PredictedFailure` events. For each:
      1. Pull a 5-minute telemetry window from TimescaleDB.
      2. Query Neo4j for a 2-hop dependency subgraph around the device.
      3. Retrieve top-K similar past incidents from ChromaDB.
      4. Compose an RCA prompt; route through LLMRouter (Haiku default).
      5. If self-rated confidence < threshold, re-run on Sonnet.
      6. Publish `IncidentReport` on `incidents.report`.

Ships: Week 5 (see ROADMAP.md).

Topics:
    in:  predictions.failure
    out: incidents.report
"""

from __future__ import annotations

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import PredictedFailure, Topic
from apps.agents.shared.llm_router import LLMRouter


class ForensicAgent(BaseAgent):
    name = "forensic"
    subscribed_topic = Topic.PREDICTIONS_FAILURE.value
    event_model = PredictedFailure

    async def on_start(self) -> None:
        await super().on_start()
        self.llm = LLMRouter(agent_name=self.name)
        # TODO(week-5): connect to Neo4j, TimescaleDB, ChromaDB.
        self.log.info("forensic.ready", note="skeleton — RCA pipeline ships Week 5")

    async def handle(self, event: PredictedFailure) -> None:  # type: ignore[override]
        self.log.info(
            "forensic.received",
            device_id=event.device_id,
            failure_kind=event.failure_kind,
            probability=event.probability,
        )
        # TODO(week-5): pull telemetry window, subgraph, similar incidents,
        #               compose prompt, call self.llm.call(...), parse JSON,
        #               persist IncidentReport to TimescaleDB, publish to bus.


if __name__ == "__main__":
    ForensicAgent.run()

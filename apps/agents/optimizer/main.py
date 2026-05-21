"""Optimizer — thermal/capacity bin-packing agent.

Purpose:
    Subscribes to incident reports + capacity requests. Uses OR-Tools CP-SAT
    to bin-pack workloads onto racks under constraints: thermal headroom
    (from physics), per-PDU power budget, anti-affinity for redundant
    workloads. Publishes `Recommendation` events.

Ships: Week 7 (see ROADMAP.md).

Topics:
    in:  incidents.report
    out: recommendations.workload_migration
"""

from __future__ import annotations

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import IncidentReport, Topic


class OptimizerAgent(BaseAgent):
    name = "optimizer"
    subscribed_topic = Topic.INCIDENTS_REPORT.value
    event_model = IncidentReport

    async def on_start(self) -> None:
        await super().on_start()
        # TODO(week-7): load current placement from Neo4j, build OR-Tools model,
        #               cache constraints (PDU capacity, rack thermal headroom).
        self.log.info("optimizer.ready", note="skeleton — OR-Tools solver ships Week 7")

    async def handle(self, event: IncidentReport) -> None:  # type: ignore[override]
        self.log.info(
            "optimizer.received",
            incident_id=str(event.incident_id),
            affected=event.affected_device_ids,
        )
        # TODO(week-7): solve bin-packing for migration candidates,
        #               publish Recommendation on recommendations.workload_migration.


if __name__ == "__main__":
    OptimizerAgent.run()

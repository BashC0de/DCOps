"""Vision — multi-modal incident analysis agent.

Purpose:
    Accepts rack photos, thermal-camera images, or console screenshots
    plus incident context. Calls Claude Sonnet vision and returns a
    structured `IncidentVisionAddendum` that the dashboard attaches to
    the existing incident record.

Ships: Week 9 (see ROADMAP.md).

Like Operator, this is request/response: the API calls in directly.

Topics:
    in:  vision.request
    out: incidents.vision_addendum
"""

from __future__ import annotations

from typing import Any

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.llm_router import LLMRouter, ModelTier, TaskClass


class VisionAgent(BaseAgent):
    name = "vision"
    subscribed_topic = "vision.request"
    event_model = None

    async def on_start(self) -> None:
        await super().on_start()
        self.llm = LLMRouter(agent_name=self.name)
        self.log.info("vision.ready", note="skeleton — multimodal ships Week 9")
        _ = (ModelTier.SONNET, TaskClass.MULTIMODAL)   # bound for Week 9 use

    async def handle(self, event: Any) -> None:
        # TODO(week-9): decode base64 image from payload, call Anthropic vision
        #               with TaskClass.MULTIMODAL (forced Sonnet), parse JSON,
        #               publish addendum on incidents.vision_addendum.
        self.log.debug("vision.tick", payload_keys=list(event.keys()) if isinstance(event, dict) else None)


if __name__ == "__main__":
    VisionAgent.run()

"""Sentinel — predictive failure detection agent.

Purpose:
    Subscribes to all `telemetry.*` events. Maintains a sliding window per
    device, runs an XGBoost classifier (trained on Backblaze SMART +
    synthetic GPU data) at a configurable cadence, and applies a rule layer
    for known-deterministic signals (GPU XID codes, ECC thresholds).
    Publishes `PredictedFailure` events on `predictions.failure`.

Ships: Week 4 (see ROADMAP.md). Until then, this skeleton only logs.

Topics:
    in:  telemetry.*
    out: predictions.failure
"""

from __future__ import annotations

from typing import Any

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import Topic


class SentinelAgent(BaseAgent):
    name = "sentinel"
    subscribed_topic = Topic.TELEMETRY_ALL.value
    event_model = None                    # raw telemetry dicts; we don't need full parsing per event

    async def on_start(self) -> None:
        await super().on_start()
        # TODO(week-4): load XGBoost model, initialize sliding-window buffers
        #               (per-device), warm rule layer (XID codes, ECC thresholds).
        self.log.info("sentinel.ready", note="skeleton — full pipeline ships Week 4")

    async def handle(self, event: Any) -> None:
        # TODO(week-4): append to per-device sliding window; at infer cadence,
        #               run model + rules; on positive, publish PredictedFailure.
        self.log.debug("sentinel.tick", payload_keys=list(event.keys()) if isinstance(event, dict) else None)


if __name__ == "__main__":
    SentinelAgent.run()

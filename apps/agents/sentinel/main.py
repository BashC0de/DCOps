"""Sentinel — predictive failure detection agent.

Loop:
    1. Subscribe to `telemetry.*` and keep a sliding window per device.
    2. Every `SENTINEL_INFER_INTERVAL_SEC` seconds, for each device that
       has new data since the last cycle:
         a. Compute the feature vector from its window.
         b. Run the deterministic rule layer.
         c. If a model is loaded, score the feature vector through XGBoost.
         d. Combine: pick the highest-confidence signal (rule OR model).
         e. If above threshold, publish a `PredictedFailure` event.
    3. Heartbeats are published by `BaseAgent` independently.

Mode fallback:
    The XGBoost model file may not exist (default state until Backblaze
    training has run). In that case `SentinelModel.enabled` is False and
    the agent still ships rule-based predictions — a Week-4-ready
    floor with no ML dependency.

Topics:
    in:  telemetry.*
    out: predictions.failure
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

from apps.agents.sentinel.features import extract_features
from apps.agents.sentinel.inference import SentinelModel
from apps.agents.sentinel.rules import RuleHit, evaluate
from apps.agents.sentinel.window import WindowStore
from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import PredictedFailure, Topic


# Probability threshold below which we suppress publication. Conservative
# default: 0.6. Tune up to reduce noise, down to catch more.
_PUBLISH_THRESHOLD = float(os.getenv("SENTINEL_PUBLISH_THRESHOLD", "0.6"))
_INFER_INTERVAL_S = float(os.getenv("SENTINEL_INFER_INTERVAL_SEC", "30"))
# Suppress re-publishing the same (device, failure_kind) within this window.
_DEDUPE_WINDOW_S = float(os.getenv("SENTINEL_DEDUPE_WINDOW_S", "300"))


@dataclass(frozen=True)
class _Decision:
    source: str               # "rule" | "model"
    failure_kind: str
    probability: float
    horizon_hours: float
    evidence: dict[str, Any]


def _classify_device_type(window_events: list[dict[str, Any]]) -> str:
    """Best-effort guess at device type from recent events."""
    for e in reversed(window_events):
        dtype = e.get("device_type")
        if isinstance(dtype, str):
            return dtype
    return "unknown"


class SentinelAgent(BaseAgent):
    name = "sentinel"
    subscribed_topic = Topic.TELEMETRY_ALL.value
    event_model = None    # raw dicts; we don't need full Pydantic parsing per event

    async def on_start(self) -> None:
        await super().on_start()
        self.store = WindowStore()
        self.model = SentinelModel()
        self.model.load()  # best-effort; sentinel runs rules-only if absent
        self._dirty: set[str] = set()
        self._recent_publishes: dict[tuple[str, str], float] = {}
        self._infer_task: asyncio.Task[None] | None = None
        self.log.info(
            "sentinel.ready",
            model_enabled=self.model.enabled,
            infer_interval_s=_INFER_INTERVAL_S,
            publish_threshold=_PUBLISH_THRESHOLD,
        )

    async def serve(self) -> None:
        """Override BaseAgent.serve so we can run the inference loop alongside."""
        await self.on_start()
        self._install_signal_handlers()
        self._infer_task = asyncio.create_task(self._inference_loop())
        try:
            async for event in self.bus.subscribe(self.subscribed_topic):
                if self._stop.is_set():
                    break
                try:
                    await self.handle(event)
                except Exception as exc:  # noqa: BLE001
                    self.log.exception("agent.handle_failed", error=str(exc))
        finally:
            if self._infer_task is not None:
                self._infer_task.cancel()
                try:
                    await self._infer_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await self.on_stop()

    async def handle(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        device_id = self.store.ingest(event)
        if device_id is not None:
            self._dirty.add(device_id)

    # --- inference cycle -------------------------------------------------------

    async def _inference_loop(self) -> None:
        """Periodically score every device that received new data."""
        while not self._stop.is_set():
            try:
                await asyncio.sleep(_INFER_INTERVAL_S)
                if not self._dirty:
                    continue
                dirty = self._dirty
                self._dirty = set()
                await self._infer_batch(dirty)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.exception("sentinel.infer_loop_error", error=str(exc))

    async def _infer_batch(self, device_ids: set[str]) -> None:
        n_scored = 0
        n_published = 0
        for device_id in device_ids:
            window = self.store.get(device_id)
            if window is None:
                continue
            events = window.recent()
            if not events:
                continue
            n_scored += 1
            decision = self._decide(device_id, events)
            if decision is None:
                continue
            if self._is_duplicate(device_id, decision.failure_kind):
                continue
            await self._publish(decision, events)
            self._mark_published(device_id, decision.failure_kind)
            n_published += 1
        if n_scored:
            self.log.debug("sentinel.cycle", scored=n_scored, published=n_published)

    def _decide(
        self,
        device_id: str,
        events: list[dict[str, Any]],
    ) -> _Decision | None:
        """Combine rules + model into at most one decision per device."""
        hits = evaluate(self.store.get(device_id))  # type: ignore[arg-type]

        model_proba = 0.0
        if self.model.enabled:
            feats = extract_features(events)
            model_proba = self.model.predict_proba(feats)

        # Find the strongest signal. Rules take precedence on ties.
        best_hit: RuleHit | None = max(hits, key=lambda h: h.probability) if hits else None
        best_score = best_hit.probability if best_hit is not None else 0.0

        if model_proba > best_score and model_proba >= _PUBLISH_THRESHOLD:
            return _Decision(
                source="model",
                failure_kind="model_predicted_failure",
                probability=model_proba,
                horizon_hours=24.0,
                evidence={"model_probability": model_proba},
            )

        if best_hit is not None and best_score >= _PUBLISH_THRESHOLD:
            evidence = dict(best_hit.evidence)
            if self.model.enabled:
                evidence["model_probability"] = model_proba
            return _Decision(
                source="rule",
                failure_kind=best_hit.failure_kind,
                probability=best_score,
                horizon_hours=best_hit.horizon_hours,
                evidence={**evidence, "rule_id": best_hit.rule_id},
            )
        return None

    async def _publish(self, decision: _Decision, events: list[dict[str, Any]]) -> None:
        last = events[-1]
        device_id = last.get("device_id", "unknown")
        evt = PredictedFailure(
            site_id=last.get("site_id", self.site_id),
            device_id=device_id,
            device_type=_classify_device_type(events),
            failure_kind=decision.failure_kind,
            probability=decision.probability,
            horizon_hours=decision.horizon_hours,
            evidence=decision.evidence,
            metadata={"source": decision.source},
        )
        try:
            await self.bus.publish(Topic.PREDICTIONS_FAILURE.value, evt)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("sentinel.publish_failed", device_id=device_id, error=str(exc))
        self.log.info(
            "sentinel.predicted",
            device_id=device_id,
            failure_kind=decision.failure_kind,
            probability=round(decision.probability, 3),
            source=decision.source,
        )

    # --- dedupe ---------------------------------------------------------------

    def _is_duplicate(self, device_id: str, failure_kind: str) -> bool:
        key = (device_id, failure_kind)
        ts = self._recent_publishes.get(key)
        if ts is None:
            return False
        return (time.monotonic() - ts) < _DEDUPE_WINDOW_S

    def _mark_published(self, device_id: str, failure_kind: str) -> None:
        self._recent_publishes[(device_id, failure_kind)] = time.monotonic()


if __name__ == "__main__":
    SentinelAgent.run()

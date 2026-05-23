"""Tests for the Sentinel decision/publish flow.

We construct the agent without going through serve(), seed the window
store with synthetic events, and call `_infer_batch` directly so we
can assert on which events are published.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from apps.agents.sentinel.main import SentinelAgent
from apps.agents.shared.events import PredictedFailure

pytestmark = pytest.mark.unit


@dataclass
class _FakeBus:
    published: list[tuple[str, Any]] = field(default_factory=list)
    _client: Any = None

    async def publish(self, topic: str, event: Any) -> int:
        self.published.append((topic, event))
        return 1

    async def close(self) -> None:
        pass


def _evt(metric: str, value: float, *, device_id: str, age_s: float = 0.0) -> dict[str, Any]:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {
        "timestamp": ts.isoformat(),
        "site_id": "frankfurt",
        "hall_id": "frankfurt-h1",
        "rack_id": "frankfurt-h1-r01",
        "device_id": device_id,
        "device_type": "gpu",
        "metric": metric,
        "value": value,
    }


@pytest.fixture
def sentinel(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("SITE_ID", "frankfurt")
    agent = SentinelAgent()
    # Replace bus + model with cheap fakes.
    bus = _FakeBus()
    agent.bus = bus
    # Manually run the parts of on_start we need (store, model, etc.).
    from apps.agents.sentinel.inference import SentinelModel
    from apps.agents.sentinel.window import WindowStore
    agent.store = WindowStore()
    agent.model = SentinelModel(model_path="/tmp/none.xgb")
    agent.model.load()  # not loaded; enabled=False
    agent._dirty = set()
    agent._recent_publishes = {}
    agent._infer_task = None
    return agent, bus


async def test_rule_fires_publish_on_fatal_xid(sentinel) -> None:
    agent, bus = sentinel
    agent.store.ingest(_evt("gpu.xid.code", 48.0, device_id="fra-h1-r07-srv03-gpu1"))
    await agent._infer_batch({"fra-h1-r07-srv03-gpu1"})

    assert len(bus.published) == 1
    topic, evt = bus.published[0]
    assert topic == "predictions.failure"
    assert isinstance(evt, PredictedFailure)
    assert evt.failure_kind == "gpu_fatal_xid"
    assert evt.probability > 0.95
    assert evt.evidence["xid_code"] == 48
    assert evt.metadata["source"] == "rule"


async def test_healthy_device_does_not_publish(sentinel) -> None:
    agent, bus = sentinel
    agent.store.ingest(_evt("gpu.temp.celsius", 70.0, device_id="d1"))
    agent.store.ingest(_evt("fan.rpm", 4200.0, device_id="d1"))
    await agent._infer_batch({"d1"})
    assert bus.published == []


async def test_dedupe_prevents_double_publish(sentinel) -> None:
    agent, bus = sentinel
    agent.store.ingest(_evt("gpu.xid.code", 43.0, device_id="d1"))
    await agent._infer_batch({"d1"})
    await agent._infer_batch({"d1"})
    assert len(bus.published) == 1


async def test_below_threshold_rule_is_suppressed(sentinel, monkeypatch) -> None:
    """Set the threshold above all rule probabilities; nothing publishes."""
    agent, bus = sentinel
    import apps.agents.sentinel.main as sm
    monkeypatch.setattr(sm, "_PUBLISH_THRESHOLD", 0.99)
    agent.store.ingest(_evt("psu.efficiency.percent", 82.0, device_id="d1"))
    for _ in range(6):
        agent.store.ingest(_evt("psu.efficiency.percent", 82.0, device_id="d1"))
    await agent._infer_batch({"d1"})
    # PSU rule prob = 0.6, below 0.99 → suppressed.
    assert bus.published == []

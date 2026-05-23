"""Integration test for the Optimizer agent's handle() flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from apps.agents.optimizer.main import OptimizerAgent
from apps.agents.shared.events import IncidentReport

pytestmark = pytest.mark.unit


@dataclass
class _FakeRedis:
    pushed: list[str] = field(default_factory=list)
    trims: list[tuple[str, int, int]] = field(default_factory=list)

    async def lpush(self, key: str, value: str) -> int:
        self.pushed.append(value)
        return len(self.pushed)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        self.trims.append((key, start, stop))


@dataclass
class _FakeBus:
    published: list[tuple[str, Any]] = field(default_factory=list)
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def publish(self, topic: str, event: Any) -> int:
        self.published.append((topic, event))
        return 1

    async def close(self) -> None:
        pass


@pytest.fixture
def optimizer(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("SITE_ID", "frankfurt")
    agent = OptimizerAgent()
    bus = _FakeBus()
    agent.bus = bus
    # Inject the lazy data clients (unconnected — handle uses synthetic fallbacks).
    from apps.agents.shared.kg_client import KnowledgeGraph
    from apps.agents.shared.ts_client import TimescaleStore
    agent.ts = TimescaleStore.from_env()
    agent.kg = KnowledgeGraph.from_env()
    return agent, bus


async def test_handle_publishes_recommendation_for_hot_rack(optimizer) -> None:
    agent, bus = optimizer
    incident = IncidentReport(
        site_id="frankfurt",
        affected_device_ids=["frankfurt-h1-r07-srv03"],
        top_hypotheses=[{"cause": "thermal", "probability": 0.8}],
        confidence=0.8,
    )
    await agent.handle(incident)

    rec_pubs = [p for p in bus.published if p[0].startswith("recommendations.")]
    assert rec_pubs, f"no recommendation published. got: {[p[0] for p in bus.published]}"
    topic, rec = rec_pubs[0]
    assert topic == "recommendations.workload_migration"
    payload = rec.model_dump()
    assert payload["kind"] == "workload_migration"
    assert payload["target_device_ids"]
    assert payload["parameters"]["moves"]


async def test_handle_skips_when_no_affected_devices(optimizer) -> None:
    agent, bus = optimizer
    incident = IncidentReport(
        site_id="frankfurt",
        affected_device_ids=[],
        top_hypotheses=[{"cause": "x", "probability": 0.5}],
        confidence=0.5,
    )
    await agent.handle(incident)
    assert bus.published == []


def test_rack_for_recovers_rack_id() -> None:
    assert OptimizerAgent._rack_for("frankfurt-h1-r07-srv03") == "frankfurt-h1-r07"
    assert OptimizerAgent._rack_for("frankfurt-h1-r07-srv03-gpu1") == "frankfurt-h1-r07"
    assert OptimizerAgent._rack_for("not-a-device-id") is None


async def test_handle_persists_to_redis_list(optimizer) -> None:
    agent, bus = optimizer
    incident = IncidentReport(
        site_id="frankfurt",
        affected_device_ids=["frankfurt-h1-r07-srv03"],
        top_hypotheses=[{"cause": "thermal", "probability": 0.8}],
        confidence=0.8,
    )
    await agent.handle(incident)
    assert bus._client.pushed, "expected at least one entry to be pushed to Redis"
    assert bus._client.trims, "expected an ltrim call to cap the list"

"""Tests for the Planner agent's tick flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from apps.agents.planner.main import PlannerAgent

pytestmark = pytest.mark.unit


@dataclass
class _FakeRedis:
    sets: list[tuple[str, str, int | None]] = field(default_factory=list)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append((key, value, ex))


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
def planner(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://invalid:6379/0")
    monkeypatch.setenv("SITE_ID", "frankfurt")
    monkeypatch.setenv("PLANNER_FORECAST_SETS", "frankfurt:power.draw.watts")
    # Reset module-level constants captured at import time.
    import apps.agents.planner.main as pm
    monkeypatch.setattr(pm, "_HORIZONS", (30,))
    agent = PlannerAgent()
    bus = _FakeBus()
    agent.bus = bus
    from apps.agents.shared.ts_client import TimescaleStore
    agent.ts = TimescaleStore.from_env()  # unconnected → uses synthetic history
    return agent, bus


async def test_forecast_one_publishes_and_caches(planner) -> None:
    agent, bus = planner
    await agent._forecast_one(site_id="frankfurt", metric="power.draw.watts")

    # Bus publish on forecasts.<horizon>.
    fc_pubs = [p for p in bus.published if p[0].startswith("forecasts.")]
    assert fc_pubs
    topic, event = fc_pubs[0]
    assert topic == "forecasts.30"
    payload = event.model_dump()
    assert "power.draw.watts" in payload["series"]

    # Redis cache hit.
    sets = bus._client.sets
    assert sets
    key, _value, _ttl = sets[0]
    assert key.startswith("forecasts:frankfurt:power.draw.watts:")
    assert key.endswith(":30")


async def test_redis_key_format() -> None:
    from apps.agents.planner.main import _redis_key
    assert _redis_key("frankfurt", "power.draw.watts", 90) == "forecasts:frankfurt:power.draw.watts:90"


async def test_synthetic_history_used_when_ts_unavailable(planner) -> None:
    agent, _ = planner
    hist = await agent._pull_history(site_id="frankfurt", metric="power.draw.watts")
    assert len(hist) > 0
    assert all(isinstance(ts, datetime) for ts, _ in hist)
    assert all(ts.tzinfo is not None for ts, _ in hist)

"""Tests for /recommendations and /forecasts API routes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app

pytestmark = pytest.mark.unit


@dataclass
class _FakeRedis:
    kv: dict[str, str] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        items = self.lists.get(key, [])
        # Redis lrange is inclusive on stop and supports negative indexing.
        if stop == -1:
            return items[start:]
        return items[start : stop + 1]


@dataclass
class _FakeBus:
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def close(self) -> None:
        pass


# --- /recommendations ---------------------------------------------------------

def test_recommendations_returns_recent_entries() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.lists["recommendations:recent"] = [
        json.dumps({"recommendation_id": "r1", "site_id": "frankfurt", "kind": "workload_migration"}),
        json.dumps({"recommendation_id": "r2", "site_id": "singapore", "kind": "workload_migration"}),
    ]
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/recommendations?limit=10")
        body = r.json()
    assert r.status_code == 200
    assert len(body["recommendations"]) == 2


def test_recommendations_filters_by_site() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.lists["recommendations:recent"] = [
        json.dumps({"recommendation_id": "r1", "site_id": "frankfurt"}),
        json.dumps({"recommendation_id": "r2", "site_id": "singapore"}),
    ]
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/recommendations?site=singapore")
        body = r.json()
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["recommendation_id"] == "r2"


def test_recommendations_degraded_without_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        body = c.get("/recommendations").json()
    assert body["status"] == "degraded"


def test_recommendation_by_id_returns_match() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.lists["recommendations:recent"] = [
        json.dumps({"recommendation_id": "abc-123", "site_id": "frankfurt"}),
    ]
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/recommendations/abc-123")
        assert r.status_code == 200
        assert r.json()["recommendation_id"] == "abc-123"


def test_recommendation_by_id_404_when_missing() -> None:
    app = create_app()
    fake = _FakeRedis()
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/recommendations/not-there")
        assert r.status_code == 404


# --- /forecasts ---------------------------------------------------------------

def test_forecast_returns_cached_payload() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.kv["forecasts:frankfurt:power.draw.watts:90"] = json.dumps(
        {
            "site_id": "frankfurt",
            "horizon_days": 90,
            "series": {"power.draw.watts": [1.0, 2.0, 3.0]},
        }
    )
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/forecasts/frankfurt/power.draw.watts?horizon_days=90")
        body = r.json()
    assert r.status_code == 200
    assert body["series"]["power.draw.watts"] == [1.0, 2.0, 3.0]


def test_forecast_missing_returns_status_missing() -> None:
    app = create_app()
    fake = _FakeRedis()
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/forecasts/frankfurt/power.draw.watts?horizon_days=90")
        body = r.json()
    assert r.status_code == 200
    assert body["status"] == "missing"


def test_forecast_degraded_without_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        body = c.get("/forecasts/frankfurt/power.draw.watts").json()
    assert body["status"] == "degraded"

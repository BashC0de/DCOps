"""Tests for /fleet/state and /federation/candidates routes."""

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
        if stop == -1:
            return items[start:]
        return items[start : stop + 1]


@dataclass
class _FakeBus:
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def close(self) -> None:
        pass


# --- /fleet/state ------------------------------------------------------------


def test_fleet_state_returns_snapshot() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.kv["fleet:snapshot"] = json.dumps(
        {"n_sites": 2, "fleet_status": "ok", "sites": []}
    )
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/fleet/state")
    assert r.status_code == 200
    body = r.json()
    assert body["fleet_status"] == "ok"
    assert body["n_sites"] == 2


def test_fleet_state_empty_when_no_snapshot_yet() -> None:
    app = create_app()
    fake = _FakeRedis()
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/fleet/state")
    assert r.status_code == 200
    assert r.json()["fleet_status"] == "empty"


def test_fleet_state_degraded_without_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        body = c.get("/fleet/state").json()
    assert body["fleet_status"] == "degraded"


# --- /federation/candidates ---------------------------------------------------


def test_candidates_returns_list_for_site() -> None:
    app = create_app()
    fake = _FakeRedis()
    fake.lists["federation:candidates:singapore"] = [
        json.dumps({"rule_id": "rule-cs-frankfurt-gpu_ecc_drift", "origin_site_id": "frankfurt"}),
        json.dumps({"rule_id": "rule-cs-mumbai-thermal_cascade", "origin_site_id": "mumbai"}),
    ]
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        r = c.get("/federation/candidates/singapore?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["site_id"] == "singapore"
    assert len(body["candidates"]) == 2


def test_candidates_degraded_without_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        body = c.get("/federation/candidates/singapore").json()
    assert body["status"] == "degraded"


def test_candidates_empty_when_none() -> None:
    app = create_app()
    fake = _FakeRedis()
    with TestClient(app) as c:
        app.state.bus = _FakeBus(_client=fake)
        body = c.get("/federation/candidates/singapore").json()
    assert body["candidates"] == []

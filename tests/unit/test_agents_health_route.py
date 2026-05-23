"""Tests for the /agents/health endpoint."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.agents.shared.base import BaseAgent
from apps.api.main import create_app

pytestmark = pytest.mark.unit


class _FakeRedis:
    """Tiny in-memory async fake supporting scan_iter + get used by the route."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        _ = ex
        self.kv[key] = value

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def scan_iter(self, match: str, count: int = 100):  # noqa: ANN201
        import fnmatch
        for k in list(self.kv.keys()):
            if fnmatch.fnmatch(k, match):
                yield k


class _FakeBus:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    async def close(self) -> None:
        pass


def test_agent_health_returns_heartbeats() -> None:
    app = create_app()
    redis_fake = _FakeRedis()
    redis_fake.kv[BaseAgent.heartbeat_key("frankfurt", "sentinel")] = json.dumps(
        {"agent": "sentinel", "site_id": "frankfurt", "last_seen_ts": 1_000.0, "pid": 42}
    )
    redis_fake.kv[BaseAgent.heartbeat_key("singapore", "forensic")] = json.dumps(
        {"agent": "forensic", "site_id": "singapore", "last_seen_ts": 999.0, "pid": 99}
    )
    with TestClient(app) as c:
        app.state.bus = _FakeBus(redis_fake)
        r = c.get("/agents/health")
        body = r.json()
    assert r.status_code == 200
    assert len(body["agents"]) == 2
    names = {a["agent"] for a in body["agents"]}
    assert names == {"sentinel", "forensic"}


def test_agent_health_site_filter() -> None:
    app = create_app()
    redis_fake = _FakeRedis()
    redis_fake.kv[BaseAgent.heartbeat_key("frankfurt", "sentinel")] = json.dumps(
        {"agent": "sentinel", "site_id": "frankfurt", "last_seen_ts": 1.0, "pid": 1}
    )
    redis_fake.kv[BaseAgent.heartbeat_key("singapore", "sentinel")] = json.dumps(
        {"agent": "sentinel", "site_id": "singapore", "last_seen_ts": 1.0, "pid": 2}
    )
    with TestClient(app) as c:
        app.state.bus = _FakeBus(redis_fake)
        r = c.get("/agents/health?site=frankfurt")
        body = r.json()
    assert len(body["agents"]) == 1
    assert body["agents"][0]["site_id"] == "frankfurt"


def test_agent_health_degraded_without_bus() -> None:
    app = create_app()
    with TestClient(app) as c:
        app.state.bus = None
        r = c.get("/agents/health")
        body = r.json()
    assert body["status"] == "degraded"
    assert body["agents"] == []

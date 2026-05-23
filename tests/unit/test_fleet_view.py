"""Tests for the fleet-view aggregator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.agents.shared.base import BaseAgent
from apps.control_plane.fleet_view import build_snapshot

pytestmark = pytest.mark.unit


@dataclass
class _FakeRedis:
    kv: dict[str, str] = field(default_factory=dict)

    async def scan_iter(self, match: str, count: int = 100):  # noqa: ANN201
        import fnmatch
        for k in list(self.kv.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)


@dataclass
class _FakeBus:
    _client: _FakeRedis = field(default_factory=_FakeRedis)

    async def close(self) -> None:
        pass


@dataclass
class _FakeTS:
    enabled: bool = True
    counts: dict[str, int] = field(default_factory=dict)
    queries: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)

    async def execute_select(self, sql, params=None, max_rows=1000):  # noqa: ANN001, ANN201
        self.queries.append((sql, params))
        if params and "incidents" in sql:
            site = params[0]
            return [{"c": self.counts.get(site, 0)}]
        return []


def _put_heartbeat(redis: _FakeRedis, site: str, agent: str, ts: float) -> None:
    key = BaseAgent.heartbeat_key(site, agent)
    redis.kv[key] = json.dumps({"agent": agent, "site_id": site, "last_seen_ts": ts, "pid": 1})


async def test_empty_snapshot_when_no_heartbeats() -> None:
    bus = _FakeBus()
    ts = _FakeTS(enabled=False)
    snap = await build_snapshot(bus, ts, now=1000.0)
    assert snap["n_sites"] == 0
    assert snap["fleet_status"] == "empty"


async def test_aggregates_live_agents_per_site(monkeypatch) -> None:
    import apps.control_plane.fleet_view as fv
    monkeypatch.setattr(fv, "_EXPECTED_AGENTS_PER_SITE", ("sentinel", "forensic"))

    bus = _FakeBus()
    # Two sites, with fresh heartbeats.
    _put_heartbeat(bus._client, "frankfurt", "sentinel", ts=995.0)
    _put_heartbeat(bus._client, "frankfurt", "forensic", ts=996.0)
    _put_heartbeat(bus._client, "singapore", "sentinel", ts=994.0)
    # Singapore is missing 'forensic'.

    ts = _FakeTS(counts={"frankfurt": 2, "singapore": 0})
    snap = await build_snapshot(bus, ts, now=1000.0)

    assert snap["n_sites"] == 2
    by_site = {s["site_id"]: s for s in snap["sites"]}
    assert by_site["frankfurt"]["status"] == "ok"
    assert by_site["frankfurt"]["incidents_last_hour"] == 2
    assert by_site["singapore"]["status"] == "degraded"
    assert "forensic" in by_site["singapore"]["missing_agents"]
    assert snap["fleet_status"] == "degraded"


async def test_stale_heartbeats_are_dropped(monkeypatch) -> None:
    import apps.control_plane.fleet_view as fv
    monkeypatch.setattr(fv, "_EXPECTED_AGENTS_PER_SITE", ("sentinel",))
    monkeypatch.setattr(fv, "_HEARTBEAT_STALE_S", 10.0)

    bus = _FakeBus()
    _put_heartbeat(bus._client, "frankfurt", "sentinel", ts=900.0)  # 100s old
    ts = _FakeTS(enabled=False)
    snap = await build_snapshot(bus, ts, now=1000.0)

    by_site = {s["site_id"]: s for s in snap["sites"]}
    assert by_site["frankfurt"]["n_live_agents"] == 0
    assert by_site["frankfurt"]["status"] == "degraded"
    assert by_site["frankfurt"]["missing_agents"] == ["sentinel"]


async def test_ts_disabled_yields_zero_incidents(monkeypatch) -> None:
    import apps.control_plane.fleet_view as fv
    monkeypatch.setattr(fv, "_EXPECTED_AGENTS_PER_SITE", ("sentinel",))

    bus = _FakeBus()
    _put_heartbeat(bus._client, "frankfurt", "sentinel", ts=999.0)
    ts = _FakeTS(enabled=False)
    snap = await build_snapshot(bus, ts, now=1000.0)
    assert snap["sites"][0]["incidents_last_hour"] == 0
    assert ts.queries == []

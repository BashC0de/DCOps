"""Tests for the API routes that read from TimescaleDB / Neo4j.

Each test swaps a fake TimescaleStore / KnowledgeGraph onto `app.state`,
then exercises the route via FastAPI's `TestClient`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app

pytestmark = pytest.mark.unit


@dataclass
class _FakeTS:
    enabled: bool = True
    rows: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    raise_value_error: bool = False

    async def execute_select(self, sql, params=None, max_rows=1000):  # noqa: ANN001, ANN201
        self.calls.append((sql, params))
        if self.raise_value_error:
            raise ValueError("forbidden")
        return list(self.rows[:max_rows])

    async def close(self):  # noqa: ANN201
        pass


@dataclass
class _FakeKG:
    enabled: bool = True
    racks: list[dict[str, Any]] = field(default_factory=list)
    _driver: Any = None  # noqa: A003 — matches the attribute on KnowledgeGraph

    async def close(self):  # noqa: ANN201
        pass


@pytest.fixture
def app_with_fakes():
    """Build the FastAPI app and install fakes onto app.state."""
    app = create_app()
    ts = _FakeTS()
    kg = _FakeKG()
    # Skip the real lifespan — we install the fakes directly.
    app.state.ts = ts
    app.state.kg = kg
    return app, ts, kg


def test_health_endpoint(app_with_fakes) -> None:
    app, _, _ = app_with_fakes
    with TestClient(app) as c:
        # Reset fakes that the lifespan may have replaced.
        app.state.ts = app_with_fakes[1]
        app.state.kg = app_with_fakes[2]
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# --- /telemetry ----------------------------------------------------------------

def test_telemetry_recent_returns_rows(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.rows = [
        {"time": "2026-05-23T00:00:00+00:00", "site_id": "frankfurt",
         "metric": "cpu.temp.celsius", "value_num": 62.5, "device_id": "srv-1"},
    ]
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/telemetry/recent?site=frankfurt&limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["site"] == "frankfurt"
        assert len(body["events"]) == 1
        assert body["events"][0]["metric"] == "cpu.temp.celsius"
    # SQL must be a SELECT against telemetry.
    assert ts.calls
    sql, params = ts.calls[0]
    assert "SELECT" in sql
    assert "FROM telemetry" in sql
    assert "frankfurt" in params


def test_telemetry_recent_degrades_when_ts_disabled(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.enabled = False
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/telemetry/recent?site=frankfurt")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["events"] == []


def test_telemetry_recent_passes_metric_and_device_filters(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    with TestClient(app) as c:
        app.state.ts = ts
        c.get("/telemetry/recent?site=frankfurt&metric=gpu.temp.celsius&device_id=srv-1")
    sql, params = ts.calls[0]
    assert "metric = %s" in sql
    assert "device_id = %s" in sql
    assert "gpu.temp.celsius" in params
    assert "srv-1" in params


def test_telemetry_range_endpoint(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.rows = [{"time": "2026-05-23T00:00:00+00:00", "device_id": "x", "value_num": 1.0}]
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/telemetry/range?site=frankfurt&metric=cpu.temp.celsius&seconds=600")
        assert r.status_code == 200
        body = r.json()
        assert body["seconds"] == 600
        assert len(body["events"]) == 1


# --- /incidents ---------------------------------------------------------------

def test_list_incidents_returns_rows(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.rows = [
        {
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "opened_at": "2026-05-23T00:00:00+00:00",
            "closed_at": None,
            "site_id": "frankfurt",
            "severity": "warn",
            "affected_devices": ["srv-1"],
            "top_hypotheses": [{"cause": "x"}],
            "confidence": 0.7,
            "llm_cost_usd": 0.0,
            "llm_model_used": "llama3.2:3b",
            "trace_id": None,
        }
    ]
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/incidents")
        assert r.status_code == 200
        body = r.json()
        assert len(body["incidents"]) == 1
        assert body["incidents"][0]["site_id"] == "frankfurt"


def test_list_incidents_filters_by_site(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    with TestClient(app) as c:
        app.state.ts = ts
        c.get("/incidents?site=singapore")
    sql, params = ts.calls[0]
    assert "WHERE site_id = %s" in sql
    assert "singapore" in params


def test_list_incidents_degrades_when_disabled(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.enabled = False
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/incidents")
        assert r.json()["status"] == "degraded"


def test_get_incident_404_when_not_found(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    ts.rows = []
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get("/incidents/11111111-1111-1111-1111-111111111111")
        assert r.status_code == 404


def test_get_incident_returns_row(app_with_fakes) -> None:
    app, ts, _ = app_with_fakes
    inc_id = "22222222-2222-2222-2222-222222222222"
    ts.rows = [
        {
            "incident_id": inc_id,
            "opened_at": "2026-05-23T00:00:00+00:00",
            "closed_at": None,
            "site_id": "frankfurt",
            "severity": "error",
            "affected_devices": ["srv-1"],
            "top_hypotheses": [],
            "confidence": 0.8,
            "llm_cost_usd": 0.0,
            "llm_model_used": "llama3.2:3b",
            "trace_id": "33333333-3333-3333-3333-333333333333",
        }
    ]
    with TestClient(app) as c:
        app.state.ts = ts
        r = c.get(f"/incidents/{inc_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["incident_id"] == inc_id
        assert body["audit_lineage_endpoint"].endswith("33333333-3333-3333-3333-333333333333")


# --- /twin --------------------------------------------------------------------

def test_twin_state_degraded_when_both_disabled(app_with_fakes) -> None:
    app, ts, kg = app_with_fakes
    ts.enabled = False
    kg.enabled = False
    with TestClient(app) as c:
        app.state.ts = ts
        app.state.kg = kg
        r = c.get("/twin/state?site=frankfurt")
        assert r.status_code == 200
        assert r.json()["status"] == "degraded"


def test_twin_state_returns_empty_when_kg_unconnected_but_ts_up(app_with_fakes) -> None:
    """KG provides topology; without it we get no racks, but the route stays 200."""
    app, ts, kg = app_with_fakes
    kg.enabled = False
    with TestClient(app) as c:
        app.state.ts = ts
        app.state.kg = kg
        r = c.get("/twin/state?site=frankfurt")
        assert r.status_code == 200
        body = r.json()
        assert body["site"] == "frankfurt"
        assert body["racks"] == []

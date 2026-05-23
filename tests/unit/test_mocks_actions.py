"""Tests for the mock vendor action endpoints."""

from __future__ import annotations

import pytest

from apps.mocks.main import app

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def test_migrate_workload_ok(client) -> None:
    r = client.post(
        "/actions/migrate_workload",
        json={
            "action_id": "a-1",
            "moves": [
                {"workload_id": "wl-x", "from_rack_id": "r1", "to_rack_id": "r2"},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["n_moves"] == 1


def test_migrate_workload_bad_request(client) -> None:
    r = client.post("/actions/migrate_workload", json={"moves": "not-a-list"})
    assert r.status_code == 400


def test_fan_speed_adjust_ok(client) -> None:
    r = client.post(
        "/actions/fan_speed_adjust",
        json={"action_id": "a-2", "device_id": "frankfurt-h1-r07-srv03", "target_fan_percent": 85},
    )
    assert r.status_code == 200
    assert r.json()["applied"] is True


def test_fan_speed_adjust_bad_request(client) -> None:
    r = client.post("/actions/fan_speed_adjust", json={"device_id": "x"})
    assert r.status_code == 400


def test_revert_ok(client) -> None:
    r = client.post("/actions/revert", json={"original_action_id": "a-1", "reason": "x"})
    assert r.status_code == 200
    assert r.json()["reverted_action_id"] == "a-1"


def test_actions_log_records_calls(client) -> None:
    client.post(
        "/actions/migrate_workload",
        json={"action_id": "log-test", "moves": []},
    )
    r = client.get("/actions/log")
    assert r.status_code == 200
    log = r.json()["actions"]
    assert any(entry.get("kind") == "migrate_workload" for entry in log)

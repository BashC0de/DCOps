"""Tests for sentinel.window — DeviceWindow + WindowStore."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from apps.agents.sentinel.window import DeviceWindow, WindowStore

pytestmark = pytest.mark.unit


def _evt(metric: str, value: float, age_s: float = 0.0, device_id: str = "d1") -> dict[str, Any]:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {
        "timestamp": ts.isoformat(),
        "device_id": device_id,
        "metric": metric,
        "value": value,
    }


def test_window_holds_events_in_order() -> None:
    w = DeviceWindow("d1", maxlen=4)
    for i in range(4):
        w.add(_evt("cpu.temp.celsius", float(i)))
    assert [e["value"] for e in w.recent()] == [0.0, 1.0, 2.0, 3.0]


def test_window_caps_at_maxlen() -> None:
    w = DeviceWindow("d1", maxlen=3)
    for i in range(5):
        w.add(_evt("cpu.temp.celsius", float(i)))
    assert [e["value"] for e in w.recent()] == [2.0, 3.0, 4.0]


def test_window_evicts_stale_by_age() -> None:
    w = DeviceWindow("d1", maxlen=100, max_age_s=5.0)
    w.add(_evt("cpu.temp.celsius", 1.0, age_s=10.0))  # stale
    w.add(_evt("cpu.temp.celsius", 2.0, age_s=10.0))  # stale
    w.add(_evt("cpu.temp.celsius", 3.0, age_s=0.0))   # fresh
    assert [e["value"] for e in w.recent()] == [3.0]


def test_window_recent_for_metric_filters() -> None:
    w = DeviceWindow("d1", maxlen=10)
    w.add(_evt("cpu.temp.celsius", 60.0))
    w.add(_evt("gpu.temp.celsius", 75.0))
    w.add(_evt("cpu.temp.celsius", 62.0))
    only_cpu = w.recent_for_metric("cpu.temp.celsius")
    assert [e["value"] for e in only_cpu] == [60.0, 62.0]


def test_window_store_routes_events_by_device() -> None:
    store = WindowStore()
    store.ingest(_evt("cpu.temp.celsius", 1.0, device_id="d1"))
    store.ingest(_evt("cpu.temp.celsius", 2.0, device_id="d1"))
    store.ingest(_evt("cpu.temp.celsius", 9.0, device_id="d2"))
    assert len(store) == 2
    assert [e["value"] for e in store.get("d1").recent()] == [1.0, 2.0]
    assert [e["value"] for e in store.get("d2").recent()] == [9.0]
    assert store.total_events() == 3


def test_window_store_ignores_event_without_device_id() -> None:
    store = WindowStore()
    out = store.ingest({"metric": "cpu.temp.celsius", "value": 1.0})
    assert out is None
    assert len(store) == 0

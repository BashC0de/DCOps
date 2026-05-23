"""Tests for sentinel.rules — every rule's happy + null case."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from apps.agents.sentinel.rules import evaluate
from apps.agents.sentinel.window import DeviceWindow

pytestmark = pytest.mark.unit


def _evt(metric: str, value: float, age_s: float = 0.0) -> dict[str, Any]:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {"timestamp": ts.isoformat(), "metric": metric, "value": value}


def _window(events: list[dict[str, Any]]) -> DeviceWindow:
    w = DeviceWindow("d1", maxlen=128)
    for e in events:
        w.add(e)
    return w


def test_evaluate_returns_empty_for_healthy_window() -> None:
    w = _window(
        [
            _evt("cpu.temp.celsius", 60.0),
            _evt("gpu.temp.celsius", 72.0),
            _evt("fan.rpm", 4200.0),
        ]
    )
    assert evaluate(w) == []


def test_fatal_xid_code_fires() -> None:
    w = _window([_evt("gpu.xid.code", 48.0)])
    hits = evaluate(w)
    assert any(h.rule_id == "gpu_fatal_xid" for h in hits)
    fatal = next(h for h in hits if h.rule_id == "gpu_fatal_xid")
    assert fatal.probability > 0.95
    assert fatal.evidence["xid_code"] == 48


def test_non_fatal_xid_does_not_fire() -> None:
    w = _window([_evt("gpu.xid.code", 1.0)])  # not in fatal set
    assert all(h.rule_id != "gpu_fatal_xid" for h in evaluate(w))


def test_uncorrectable_ecc_fires_on_nonzero() -> None:
    w = _window([_evt("gpu.ecc.uncorrectable", 1.0)])
    hits = evaluate(w)
    assert any(h.rule_id == "gpu_uncorrectable_ecc" for h in hits)


def test_correctable_ecc_storm_threshold() -> None:
    # Sum > 10_000 across the window.
    events = [_evt("gpu.ecc.correctable", 4_000.0) for _ in range(3)]
    w = _window(events)
    hits = evaluate(w)
    assert any(h.rule_id == "gpu_correctable_ecc_storm" for h in hits)


def test_gpu_thermal_runaway_fires_above_90c() -> None:
    w = _window([_evt("gpu.temp.celsius", 92.0)])
    hits = evaluate(w)
    assert any(h.rule_id == "gpu_thermal_runaway" for h in hits)


def test_fan_stuck_hot_cpu_fires() -> None:
    w = _window(
        [
            _evt("fan.rpm", 0.0),
            _evt("cpu.temp.celsius", 82.0),
        ]
    )
    hits = evaluate(w)
    assert any(h.rule_id == "fan_stuck_hot_cpu" for h in hits)


def test_fan_stuck_does_not_fire_when_cpu_cool() -> None:
    w = _window(
        [
            _evt("fan.rpm", 0.0),
            _evt("cpu.temp.celsius", 50.0),
        ]
    )
    assert all(h.rule_id != "fan_stuck_hot_cpu" for h in evaluate(w))


def test_disk_reallocated_burst_fires() -> None:
    w = _window(
        [
            _evt("disk.reallocated.sectors", 10.0, age_s=30),
            _evt("disk.reallocated.sectors", 100.0, age_s=0),
        ]
    )
    hits = evaluate(w)
    assert any(h.rule_id == "disk_reallocated_burst" for h in hits)


def test_psu_efficiency_drop_fires_when_below_85() -> None:
    events = [_evt("psu.efficiency.percent", 82.0) for _ in range(6)]
    w = _window(events)
    hits = evaluate(w)
    assert any(h.rule_id == "psu_efficiency_drop" for h in hits)

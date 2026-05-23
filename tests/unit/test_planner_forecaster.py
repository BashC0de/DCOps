"""Tests for the Planner's forecasting wrapper.

We test the linear-fallback path directly. The Prophet path is exercised
via integration tests when a live Timescale + Prophet install is present;
unit tests here ensure the fallback ships a useful result.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.agents.planner.forecaster import ForecastResult, forecast

pytestmark = pytest.mark.unit


def _series(days: int, base: float, slope_per_day: float = 0.0) -> list[tuple[datetime, float]]:
    now = datetime.now(timezone.utc)
    return [
        (now - timedelta(days=days - i), base + slope_per_day * i)
        for i in range(days)
    ]


def test_forecast_empty_history_returns_empty_method() -> None:
    out = forecast(site_id="x", metric="m", history=[], horizon_days=10)
    assert isinstance(out, ForecastResult)
    assert out.method == "empty"
    assert out.points == []


def test_forecast_short_history_uses_linear_fallback() -> None:
    history = _series(days=5, base=100.0, slope_per_day=1.0)
    out = forecast(site_id="x", metric="m", history=history, horizon_days=7)
    assert out.method == "linear_fallback"
    assert len(out.points) == 7
    # Should project a rising trend.
    assert out.values[-1] > out.values[0]
    # CI bounds bracket the value.
    for p in out.points:
        assert p.yhat_lower <= p.value <= p.yhat_upper


def test_forecast_flat_history_returns_flat_projection() -> None:
    history = _series(days=5, base=50.0)
    out = forecast(site_id="x", metric="m", history=history, horizon_days=5)
    assert out.method == "linear_fallback"
    # Values shouldn't drift wildly from the input baseline.
    assert all(abs(v - 50.0) < 1.0 for v in out.values)


def test_forecast_long_history_attempts_prophet_or_falls_back() -> None:
    """With enough history and a real Prophet, use it; otherwise fall back."""
    history = _series(days=40, base=200.0, slope_per_day=0.5)
    out = forecast(site_id="x", metric="m", history=history, horizon_days=30)
    # Either Prophet succeeds or we fall back to linear — both produce 30 points.
    assert len(out.points) == 30
    assert out.method in {"prophet", "linear_fallback"}
    # Trend should still be upward.
    assert out.values[-1] > out.values[0]


def test_forecast_result_lengths_align() -> None:
    history = _series(days=10, base=100.0, slope_per_day=2.0)
    out = forecast(site_id="x", metric="m", history=history, horizon_days=12)
    assert len(out.values) == len(out.lowers) == len(out.uppers) == len(out.points)

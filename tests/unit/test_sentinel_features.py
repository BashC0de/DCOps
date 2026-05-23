"""Tests for sentinel.features."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from apps.agents.sentinel.features import (
    FEATURE_METRICS,
    extract_features,
    feature_columns,
    feature_vector,
)

pytestmark = pytest.mark.unit


def _evt(metric: str, value: float, age_s: float = 0.0) -> dict[str, Any]:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {"timestamp": ts.isoformat(), "metric": metric, "value": value}


def test_feature_columns_is_stable_and_unique() -> None:
    cols = feature_columns()
    assert len(cols) == len(set(cols))
    expected = len(FEATURE_METRICS) * 4  # mean/max/slope/count per metric
    assert len(cols) == expected


def test_extract_features_returns_nan_for_missing_metrics() -> None:
    feats = extract_features([])
    for c in feature_columns():
        v = feats[c]
        # count columns default to 0; other stats to NaN.
        if c.endswith("__count"):
            assert v == 0.0
        else:
            assert math.isnan(v)


def test_extract_features_computes_mean_max_count() -> None:
    events = [
        _evt("cpu.temp.celsius", 60.0, age_s=20),
        _evt("cpu.temp.celsius", 70.0, age_s=10),
        _evt("cpu.temp.celsius", 80.0, age_s=0),
    ]
    feats = extract_features(events)
    assert feats["cpu.temp.celsius__count"] == 3.0
    assert feats["cpu.temp.celsius__mean"] == pytest.approx(70.0)
    assert feats["cpu.temp.celsius__max"] == 80.0


def test_extract_features_slope_per_min_is_positive_on_rising_temp() -> None:
    # 60 → 80 over 20s = +1 C/s = +60 C/min.
    events = [
        _evt("cpu.temp.celsius", 60.0, age_s=20),
        _evt("cpu.temp.celsius", 80.0, age_s=0),
    ]
    feats = extract_features(events)
    slope = feats["cpu.temp.celsius__slope_per_min"]
    assert slope > 0
    # Allow some tolerance — the timestamps are taken from wall clock.
    assert 30 < slope < 120


def test_feature_vector_aligns_with_columns() -> None:
    events = [_evt("gpu.temp.celsius", 70.0)]
    feats = extract_features(events)
    vec = feature_vector(feats)
    cols = feature_columns()
    assert len(vec) == len(cols)
    idx = cols.index("gpu.temp.celsius__mean")
    assert vec[idx] == pytest.approx(70.0)

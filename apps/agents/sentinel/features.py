"""Feature extraction over a device's telemetry window.

`extract_features(window)` returns a fixed-shape dict of floats — one
column per (canonical_metric, statistic) — suitable as a single row
input to the XGBoost classifier.

Statistics per metric: mean, max, slope_per_min, count.

Missing metrics in the window contribute NaN (XGBoost handles NaN
natively). The schema is stable across calls so the model sees the
same feature vector shape every time.
"""

from __future__ import annotations

import math
from typing import Any

from apps.ingestion.schema import CanonicalMetric


# Subset of CanonicalMetric we extract features for. Keeping this narrow
# keeps the model dimensionality low.
FEATURE_METRICS: tuple[CanonicalMetric, ...] = (
    CanonicalMetric.CPU_TEMP_CELSIUS,
    CanonicalMetric.GPU_TEMP_CELSIUS,
    CanonicalMetric.GPU_POWER_WATTS,
    CanonicalMetric.GPU_UTIL_PERCENT,
    CanonicalMetric.GPU_ECC_CORRECTABLE,
    CanonicalMetric.GPU_ECC_UNCORRECTABLE,
    CanonicalMetric.GPU_XID_CODE,
    CanonicalMetric.FAN_RPM,
    CanonicalMetric.POWER_DRAW_WATTS,
    CanonicalMetric.PSU_EFFICIENCY_PERCENT,
    CanonicalMetric.DISK_REALLOCATED_SECTORS,
    CanonicalMetric.DISK_PENDING_SECTORS,
    CanonicalMetric.NET_ERR_IN,
)

_STATS: tuple[str, ...] = ("mean", "max", "slope_per_min", "count")


def feature_columns() -> list[str]:
    """Return the deterministic feature-vector column names."""
    cols: list[str] = []
    for m in FEATURE_METRICS:
        for stat in _STATS:
            cols.append(f"{m.value}__{stat}")
    return cols


def _numeric_values(events: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Pairs of (timestamp_seconds_offset, value) for numeric samples only.

    Timestamp offset is relative to the oldest sample, in seconds — used
    by the slope calc.
    """
    out: list[tuple[float, float]] = []
    base_ts: float | None = None
    for e in events:
        ts_raw = e.get("timestamp")
        value = e.get("value")
        if not isinstance(value, (int, float)):
            continue
        if isinstance(ts_raw, str):
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.timestamp()
        elif hasattr(ts_raw, "timestamp"):
            ts = ts_raw.timestamp()
        else:
            continue
        if base_ts is None:
            base_ts = ts
        out.append((ts - base_ts, float(value)))
    return out


def _slope_per_min(pairs: list[tuple[float, float]]) -> float:
    """Least-squares slope (value units per minute). NaN with < 2 points."""
    n = len(pairs)
    if n < 2:
        return math.nan
    mean_x = sum(p[0] for p in pairs) / n
    mean_y = sum(p[1] for p in pairs) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    den = sum((x - mean_x) ** 2 for x, _ in pairs)
    if den <= 0.0:
        return 0.0
    slope_per_sec = num / den
    return slope_per_sec * 60.0


def _metric_features(
    window_events: list[dict[str, Any]],
    metric: CanonicalMetric,
) -> dict[str, float]:
    subset = [e for e in window_events if e.get("metric") == metric.value]
    pairs = _numeric_values(subset)
    if not pairs:
        return {
            f"{metric.value}__mean": math.nan,
            f"{metric.value}__max": math.nan,
            f"{metric.value}__slope_per_min": math.nan,
            f"{metric.value}__count": 0.0,
        }
    values = [v for _, v in pairs]
    return {
        f"{metric.value}__mean": sum(values) / len(values),
        f"{metric.value}__max": max(values),
        f"{metric.value}__slope_per_min": _slope_per_min(pairs),
        f"{metric.value}__count": float(len(values)),
    }


def extract_features(window_events: list[dict[str, Any]]) -> dict[str, float]:
    """Return a single-row feature dict for the model.

    Stable column order: every call returns the same keys regardless of
    which metrics happened to be present. Missing metrics → NaN.
    """
    feats: dict[str, float] = {}
    for metric in FEATURE_METRICS:
        feats.update(_metric_features(window_events, metric))
    return feats


def feature_vector(feats: dict[str, float]) -> list[float]:
    """Order `feats` according to `feature_columns()`, returning a list."""
    cols = feature_columns()
    return [feats.get(c, math.nan) for c in cols]


__all__ = [
    "FEATURE_METRICS",
    "feature_columns",
    "extract_features",
    "feature_vector",
]

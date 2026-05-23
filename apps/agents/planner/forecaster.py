"""Prophet wrapper for capacity forecasting.

Pure function: takes a list of `(timestamp, value)` history and a horizon,
returns a `ForecastResult` with daily projections plus 80% confidence
intervals. The Planner agent main loop calls this per (site, metric) combo.

Prophet is heavy to load (~1.5s) and slow on huge series — Planner runs
hourly, not on every event, and caps the history window. If Prophet is
unavailable (missing dep, broken install), we fall back to a linear
extrapolation so the demo still renders something.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    value: float
    yhat_lower: float
    yhat_upper: float


@dataclass
class ForecastResult:
    site_id: str
    metric: str
    horizon_days: int
    points: list[ForecastPoint] = field(default_factory=list)
    method: str = "prophet"             # "prophet" | "linear_fallback"
    notes: str = ""

    @property
    def values(self) -> list[float]:
        return [p.value for p in self.points]

    @property
    def lowers(self) -> list[float]:
        return [p.yhat_lower for p in self.points]

    @property
    def uppers(self) -> list[float]:
        return [p.yhat_upper for p in self.points]


def forecast(
    *,
    site_id: str,
    metric: str,
    history: Sequence[tuple[datetime, float]],
    horizon_days: int = 90,
    freq: str = "h",
) -> ForecastResult:
    """Generate a Prophet forecast (or linear fallback) for `metric` at `site_id`.

    Args:
        history: Sequence of (timestamp, value). Must be timezone-aware.
        horizon_days: How far to project.
        freq: Pandas frequency string for the future grid.
    """
    if not history:
        return ForecastResult(
            site_id=site_id, metric=metric, horizon_days=horizon_days,
            method="empty", notes="no history provided",
        )

    history_pairs = [(t, float(v)) for t, v in history if isinstance(v, (int, float))]
    if len(history_pairs) < 8:
        return _linear_fallback(
            site_id=site_id, metric=metric, history=history_pairs,
            horizon_days=horizon_days,
            notes="insufficient history for Prophet (< 8 points)",
        )

    try:
        return _prophet_forecast(
            site_id=site_id, metric=metric,
            history=history_pairs,
            horizon_days=horizon_days, freq=freq,
        )
    except Exception as exc:  # noqa: BLE001
        return _linear_fallback(
            site_id=site_id, metric=metric, history=history_pairs,
            horizon_days=horizon_days,
            notes=f"prophet failed: {exc!r}",
        )


# --- Prophet path --------------------------------------------------------------

def _prophet_forecast(
    *,
    site_id: str,
    metric: str,
    history: list[tuple[datetime, float]],
    horizon_days: int,
    freq: str,
) -> ForecastResult:
    import pandas as pd
    from prophet import Prophet

    df = pd.DataFrame(
        [
            {"ds": _to_naive_utc(t), "y": v}
            for t, v in history
        ]
    )
    # Drop duplicate timestamps (Prophet refuses).
    df = df.drop_duplicates(subset=["ds"]).sort_values("ds")

    m = Prophet(
        interval_width=0.8,
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        changepoint_prior_scale=0.05,
    )
    m.fit(df)

    # Daily forecast points over the horizon, regardless of `freq` granularity.
    future = m.make_future_dataframe(periods=horizon_days, freq="D", include_history=False)
    pred = m.predict(future)

    points: list[ForecastPoint] = [
        ForecastPoint(
            timestamp=_to_aware_utc(row.ds),
            value=float(row.yhat),
            yhat_lower=float(row.yhat_lower),
            yhat_upper=float(row.yhat_upper),
        )
        for row in pred.itertuples()
    ]
    return ForecastResult(
        site_id=site_id, metric=metric, horizon_days=horizon_days,
        points=points, method="prophet",
    )


# --- Linear fallback -----------------------------------------------------------

def _linear_fallback(
    *,
    site_id: str,
    metric: str,
    history: list[tuple[datetime, float]],
    horizon_days: int,
    notes: str = "",
) -> ForecastResult:
    """Least-squares linear fit; flat extrapolation if too few points."""
    n = len(history)
    if n == 0:
        return ForecastResult(
            site_id=site_id, metric=metric, horizon_days=horizon_days,
            method="empty", notes=notes,
        )

    # x = seconds since first sample; y = value.
    t0 = history[0][0].timestamp()
    xs = [t[0].timestamp() - t0 for t in history]
    ys = [t[1] for t in history]

    if n < 2:
        slope = 0.0
        intercept = ys[0]
        residual_std = 0.0
    else:
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = num / den if den > 0 else 0.0
        intercept = mean_y - slope * mean_x
        residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=False)]
        var = sum(r ** 2 for r in residuals) / max(1, n - 2)
        residual_std = math.sqrt(var)

    last_ts = history[-1][0]
    points: list[ForecastPoint] = []
    for day in range(1, horizon_days + 1):
        ts = last_ts + timedelta(days=day)
        x = ts.timestamp() - t0
        yhat = intercept + slope * x
        # ±1 sigma envelope as a rough 68% CI (caller can rescale).
        points.append(
            ForecastPoint(
                timestamp=ts.astimezone(timezone.utc),
                value=yhat,
                yhat_lower=yhat - residual_std,
                yhat_upper=yhat + residual_std,
            )
        )
    return ForecastResult(
        site_id=site_id, metric=metric, horizon_days=horizon_days,
        points=points, method="linear_fallback", notes=notes,
    )


# --- helpers -------------------------------------------------------------------

def _to_naive_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(timezone.utc).replace(tzinfo=None)


def _to_aware_utc(ts: Any) -> datetime:
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if not isinstance(ts, datetime):
        ts = datetime.fromisoformat(str(ts))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


__all__ = ["ForecastPoint", "ForecastResult", "forecast"]

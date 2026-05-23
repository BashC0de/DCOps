"""Planner forecasts read endpoint.

Reads cached forecasts (`forecasts:<site>:<metric>:<horizon>`) the
Planner agent writes on every tick. The agent runs hourly; the cache TTL
is ~2 hours so the latest forecast is always available.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Path, Query, Request

router = APIRouter()


@router.get("/{site}/{metric}")
async def get_forecast(
    request: Request,
    site: str = Path(..., description="Site id, e.g. 'frankfurt'"),
    metric: str = Path(..., description="Canonical metric name"),
    horizon_days: int = Query(90, ge=1, le=180),
) -> dict[str, Any]:
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        return {"site": site, "metric": metric, "horizon_days": horizon_days,
                "series": {}, "status": "degraded"}

    key = f"forecasts:{site}:{metric}:{horizon_days}"
    try:
        raw = await client.get(key)
    except Exception:  # noqa: BLE001
        return {"site": site, "metric": metric, "horizon_days": horizon_days,
                "series": {}, "status": "degraded"}

    if raw is None:
        return {"site": site, "metric": metric, "horizon_days": horizon_days,
                "series": {}, "status": "missing",
                "hint": "planner hasn't produced this forecast yet"}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"site": site, "metric": metric, "horizon_days": horizon_days,
                "series": {}, "status": "corrupt"}

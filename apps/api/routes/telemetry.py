"""Telemetry read endpoints.

Backed by `TimescaleStore`. Routes return an empty `events` list (and
`status="degraded"`) when the store isn't connected, so the dashboard
stays alive even when the data plane is down.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/recent")
async def recent(
    request: Request,
    site: str = Query(..., description="Site id, e.g. 'frankfurt'"),
    metric: str | None = Query(None, description="Optional canonical metric filter"),
    device_id: str | None = Query(None, description="Optional device id filter"),
    limit: int = Query(100, ge=1, le=10_000),
) -> dict[str, Any]:
    """Return the latest `limit` telemetry rows for a site (descending by time)."""
    ts = getattr(request.app.state, "ts", None)
    if ts is None or not ts.enabled:
        return {"site": site, "limit": limit, "events": [], "status": "degraded"}

    clauses = ["site_id = %s"]
    params: list[Any] = [site]
    if metric is not None:
        clauses.append("metric = %s")
        params.append(metric)
    if device_id is not None:
        clauses.append("device_id = %s")
        params.append(device_id)
    where = " AND ".join(clauses)

    sql = (
        f"SELECT time, site_id, hall_id, rack_id, device_id, device_type, "
        f"metric, value_num, value_str, unit, severity, metadata "
        f"FROM telemetry WHERE {where} ORDER BY time DESC LIMIT %s"
    )
    params.append(limit)

    rows = await ts.execute_select(sql, tuple(params), max_rows=limit)
    # Stringify timestamps + UUIDs for JSON safety.
    for r in rows:
        if "time" in r and r["time"] is not None:
            r["time"] = str(r["time"])
    return {"site": site, "limit": limit, "events": rows}


@router.get("/range")
async def range_(
    request: Request,
    site: str = Query(...),
    metric: str = Query(...),
    seconds: int = Query(3600, ge=1, le=86_400),
    device_id: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10_000),
) -> dict[str, Any]:
    """Time-window slice — last `seconds` for a given site + metric."""
    ts = getattr(request.app.state, "ts", None)
    if ts is None or not ts.enabled:
        return {"site": site, "metric": metric, "events": [], "status": "degraded"}

    clauses = ["site_id = %s", "metric = %s", "time >= NOW() - (%s || ' seconds')::interval"]
    params: list[Any] = [site, metric, str(seconds)]
    if device_id is not None:
        clauses.append("device_id = %s")
        params.append(device_id)
    where = " AND ".join(clauses)

    sql = (
        f"SELECT time, device_id, value_num, unit, severity "
        f"FROM telemetry WHERE {where} ORDER BY time ASC LIMIT %s"
    )
    params.append(limit)

    rows = await ts.execute_select(sql, tuple(params), max_rows=limit)
    for r in rows:
        if "time" in r and r["time"] is not None:
            r["time"] = str(r["time"])
    return {"site": site, "metric": metric, "seconds": seconds, "events": rows}

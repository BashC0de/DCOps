"""Telemetry read endpoints. Ships: Week 3 (real Timescale queries)."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/recent")
async def recent(
    site: str = Query(..., description="Site id, e.g. 'frankfurt'"),
    metric: str | None = Query(None, description="Optional canonical metric filter"),
    limit: int = Query(100, ge=1, le=10_000),
) -> dict[str, object]:
    """Return the latest `limit` telemetry rows for a site. Skeleton until Week 3."""
    # TODO(week-3): SELECT … FROM telemetry WHERE site_id = $1 [AND metric = $2]
    #               ORDER BY time DESC LIMIT $3
    return {"site": site, "metric": metric, "limit": limit, "events": []}

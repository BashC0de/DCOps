"""Incident read endpoints + audit lineage."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("")
async def list_incidents(
    request: Request,
    site: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Recent incidents across (or filtered to) a site, descending by opened_at."""
    ts = getattr(request.app.state, "ts", None)
    if ts is None or not ts.enabled:
        return {"site": site, "limit": limit, "incidents": [], "status": "degraded"}

    if site is None:
        sql = (
            "SELECT incident_id, opened_at, closed_at, site_id, severity, "
            "affected_devices, top_hypotheses, confidence, llm_cost_usd, "
            "llm_model_used, trace_id "
            "FROM incidents ORDER BY opened_at DESC LIMIT %s"
        )
        params: tuple[Any, ...] = (limit,)
    else:
        sql = (
            "SELECT incident_id, opened_at, closed_at, site_id, severity, "
            "affected_devices, top_hypotheses, confidence, llm_cost_usd, "
            "llm_model_used, trace_id "
            "FROM incidents WHERE site_id = %s ORDER BY opened_at DESC LIMIT %s"
        )
        params = (site, limit)

    rows = await ts.execute_select(sql, params, max_rows=limit)
    for r in rows:
        for k in ("incident_id", "trace_id", "opened_at", "closed_at"):
            if r.get(k) is not None:
                r[k] = str(r[k])
    return {"site": site, "limit": limit, "incidents": rows}


@router.get("/{incident_id}")
async def get_incident(request: Request, incident_id: UUID) -> dict[str, Any]:
    """Full incident detail — single row from the `incidents` table.

    Audit lineage (join with `audit.events` by trace_id) lands when the
    audit stream → MinIO archive is queryable. For now the route returns
    the row + a hint that a separate audit endpoint will follow.
    """
    ts = getattr(request.app.state, "ts", None)
    if ts is None or not ts.enabled:
        raise HTTPException(status_code=503, detail="timescale unavailable")

    sql = (
        "SELECT incident_id, opened_at, closed_at, site_id, severity, "
        "affected_devices, top_hypotheses, confidence, llm_cost_usd, "
        "llm_model_used, trace_id "
        "FROM incidents WHERE incident_id = %s LIMIT 1"
    )
    rows = await ts.execute_select(sql, (str(incident_id),), max_rows=1)
    if not rows:
        raise HTTPException(status_code=404, detail="incident not found")

    row = rows[0]
    for k in ("incident_id", "trace_id", "opened_at", "closed_at"):
        if row.get(k) is not None:
            row[k] = str(row[k])
    row["audit_lineage_endpoint"] = (
        # TODO(week-5+): replace with a real /audit/{trace_id} endpoint backed
        # by either Redis Streams range or the MinIO archive.
        f"/audit/by-trace/{row.get('trace_id')}" if row.get("trace_id") else None
    )
    return row

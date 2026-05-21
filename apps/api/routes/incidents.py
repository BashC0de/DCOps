"""Incident read endpoints + audit lineage. Ships: Week 5."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("")
async def list_incidents(site: str | None = None, limit: int = 50) -> dict[str, object]:
    """Recent incidents across (or filtered to) a site. Skeleton until Week 5."""
    # TODO(week-5): SELECT * FROM incidents WHERE site_id = $1 ORDER BY opened_at DESC.
    return {"site": site, "limit": limit, "incidents": []}


@router.get("/{incident_id}")
async def get_incident(incident_id: UUID) -> dict[str, object]:
    """Full incident detail incl. RCA + audit lineage. Skeleton until Week 5."""
    # TODO(week-5): join incidents + audit.events rows for trace_id.
    raise HTTPException(status_code=404, detail="not_implemented")

"""Federation endpoints — cross-site rule candidates.

Reads the per-target lists the cross-site correlator writes
(`federation:candidates:<site_id>`).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Path, Query, Request

router = APIRouter()


@router.get("/candidates/{site_id}")
async def list_candidates(
    request: Request,
    site_id: str = Path(..., description="The receiving site"),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Recent rule candidates propagated to `site_id`."""
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        return {"site_id": site_id, "candidates": [], "status": "degraded"}

    key = f"federation:candidates:{site_id}"
    try:
        raw_entries = await client.lrange(key, 0, limit - 1)
    except Exception:  # noqa: BLE001
        return {"site_id": site_id, "candidates": [], "status": "degraded"}

    out: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return {"site_id": site_id, "candidates": out}

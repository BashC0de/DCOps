"""Optimizer recommendations read endpoint.

Reads the Redis-cached list (`recommendations:recent`) the Optimizer
agent writes on every successful solve. Newest entries first.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()

_REDIS_KEY = "recommendations:recent"


@router.get("")
async def list_recommendations(
    request: Request,
    site: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        return {"recommendations": [], "status": "degraded"}

    try:
        raw_entries = await client.lrange(_REDIS_KEY, 0, limit * 4)
    except Exception:  # noqa: BLE001
        return {"recommendations": [], "status": "degraded"}

    out: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if site is not None and entry.get("site_id") != site:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return {"site": site, "limit": limit, "recommendations": out}


@router.get("/{recommendation_id}")
async def get_recommendation(request: Request, recommendation_id: str) -> dict[str, Any]:
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        raise HTTPException(status_code=503, detail="event bus unavailable")
    try:
        raw_entries = await client.lrange(_REDIS_KEY, 0, -1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    for raw in raw_entries:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if str(entry.get("recommendation_id", "")) == recommendation_id:
            return entry
    raise HTTPException(status_code=404, detail="recommendation not found")

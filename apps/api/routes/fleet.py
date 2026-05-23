"""Fleet view endpoint.

Reads the `fleet:snapshot` key the control-plane fleet-view aggregator
writes every ~5 seconds.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()

_SNAPSHOT_KEY = "fleet:snapshot"


@router.get("/state")
async def fleet_state(request: Request) -> dict[str, Any]:
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        return {"sites": [], "fleet_status": "degraded"}
    try:
        raw = await client.get(_SNAPSHOT_KEY)
    except Exception:  # noqa: BLE001
        return {"sites": [], "fleet_status": "degraded"}
    if raw is None:
        return {"sites": [], "fleet_status": "empty", "hint": "control-plane not running"}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"sites": [], "fleet_status": "corrupt"}

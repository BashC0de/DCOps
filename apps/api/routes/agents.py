"""Agent health + recent-decision endpoints.

`GET /agents/health` reads the `agent:<site>:<name>:heartbeat` keys
written by every `BaseAgent` via its heartbeat task. The keys carry a
TTL — if the agent dies, its heartbeat drops off automatically.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def agent_health(request: Request, site: str | None = None) -> dict[str, Any]:
    """Latest heartbeat per agent. Optionally filter to one site."""
    bus = getattr(request.app.state, "bus", None)
    client = getattr(bus, "_client", None) if bus is not None else None
    if client is None:
        return {"agents": [], "status": "degraded"}

    pattern = f"agent:{site}:*:heartbeat" if site else "agent:*:*:heartbeat"
    try:
        keys = [k async for k in client.scan_iter(match=pattern, count=200)]
    except Exception:  # noqa: BLE001
        return {"agents": [], "status": "degraded"}

    out: list[dict[str, Any]] = []
    now = time.time()
    for key in keys:
        try:
            raw = await client.get(key)
        except Exception:  # noqa: BLE001
            continue
        if raw is None:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        last_seen = float(payload.get("last_seen_ts", 0.0))
        out.append(
            {
                "agent": payload.get("agent", "unknown"),
                "site_id": payload.get("site_id", "unknown"),
                "last_seen_ts": last_seen,
                "stale_seconds": max(0.0, now - last_seen),
                "pid": payload.get("pid"),
            }
        )
    out.sort(key=lambda x: (x["site_id"], x["agent"]))
    return {"agents": out}

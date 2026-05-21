"""Agent health + recent-decision endpoints. Ships: Week 4."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def agent_health() -> dict[str, object]:
    """Last-seen heartbeat per agent. Skeleton until Week 4."""
    # TODO(week-4): read `agent:<name>:heartbeat` keys from Redis.
    return {"agents": []}

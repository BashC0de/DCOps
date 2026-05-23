"""Vision analysis endpoint. Proxies to the Vision agent.

Flow mirrors `/query`:
    1. Generate `request_id` (UUID).
    2. Start a subscriber on `incidents.vision_addendum`, signal ready.
    3. Publish `vision.request` with the question + images.
    4. Return the first matching addendum (or 504 on timeout).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


_VISION_TIMEOUT_S = float(os.getenv("VISION_QUERY_TIMEOUT_S", "60"))
_SUBSCRIBE_READY_TIMEOUT_S = 5.0


class VisionRequest(BaseModel):
    context: str = Field(min_length=1)
    images: list[str] = Field(
        default_factory=list,
        description="Base64-encoded image payloads. At least one is recommended.",
    )
    incident_id: UUID | None = None


@router.post("/analyze")
async def analyze(request: Request, req: VisionRequest) -> dict[str, Any]:
    """Send `req` to Vision and return its `IncidentVisionAddendum` payload."""
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="event bus unavailable")

    request_id = uuid4()
    ready = asyncio.Event()
    waiter = asyncio.create_task(_wait_for_addendum(bus, str(request_id), ready, _VISION_TIMEOUT_S))

    try:
        try:
            await asyncio.wait_for(ready.wait(), timeout=_SUBSCRIBE_READY_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            waiter.cancel()
            raise HTTPException(status_code=503, detail="subscriber setup timeout") from exc

        payload = _VisionRequestEnvelope(
            request_id=str(request_id),
            context=req.context,
            images=req.images,
            incident_id=str(req.incident_id) if req.incident_id else None,
        )
        await bus.publish("vision.request", payload)

        try:
            return await waiter
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"vision did not respond within {_VISION_TIMEOUT_S:.0f}s",
            ) from exc
    finally:
        if not waiter.done():
            waiter.cancel()


async def _wait_for_addendum(
    bus: Any,
    request_id: str,
    ready: asyncio.Event,
    timeout_s: float,
) -> dict[str, Any]:
    """Subscribe to `incidents.vision_addendum`, signal ready, return first match.

    Match is strict: we look for our `request_id` echoed in `metadata`. The
    Vision agent's `_publish` copies it from the incoming request envelope.
    """
    async def _consume() -> dict[str, Any]:
        iterator = bus.subscribe("incidents.vision_addendum").__aiter__()
        first_event_task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0.05)
        ready.set()

        try:
            first = await first_event_task
            if _matches(first, request_id):
                return _to_dict(first)
        except StopAsyncIteration:
            return {}

        async for event in iterator:
            if _matches(event, request_id):
                return _to_dict(event)
        return {}

    return await asyncio.wait_for(_consume(), timeout=timeout_s)


def _matches(event: Any, request_id: str) -> bool:
    if not isinstance(event, dict):
        return False
    md = event.get("metadata") or {}
    if isinstance(md, dict) and str(md.get("request_id", "")) == request_id:
        return True
    return False


def _to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    return {}


class _VisionRequestEnvelope(BaseModel):
    """Pydantic shape the Vision agent's `_extract_request` accepts."""

    request_id: str
    context: str
    images: list[str] = Field(default_factory=list)
    incident_id: str | None = None

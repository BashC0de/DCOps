"""Natural-language query endpoint. Proxies to the Operator agent.

Flow:
    1. Generate a `request_id` (UUID).
    2. Start a background task that subscribes to `query.result` and signals
       a `ready` event once the Redis psubscribe completes.
    3. Wait on `ready` so we don't publish before the subscription is wired.
    4. Publish to `query.<request_id>` with `{question, request_id}`.
    5. The waiter ignores mismatched request_ids; returns the first matching
       `QueryResult` payload (or 504 on timeout).

Why the ready-signal dance:
    `bus.subscribe()` is an async generator. `psubscribe` to Redis only
    happens after the consumer's first `__anext__()`. A naive `sleep(0)`
    doesn't reliably get us past that point on every event-loop scheduler.
    The Event makes the ordering explicit and the test deterministic.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


_QUERY_TIMEOUT_S = float(os.getenv("OPERATOR_QUERY_TIMEOUT_S", "30"))
_SUBSCRIBE_READY_TIMEOUT_S = 5.0


class QueryRequest(BaseModel):
    question: str
    site: str | None = None


@router.post("")
async def nl_query(request: Request, req: QueryRequest) -> dict[str, Any]:
    """Send `req.question` to Operator and return its `QueryResult` payload."""
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="event bus unavailable")

    request_id = uuid4()
    return await _round_trip(bus, request_id, req)


async def _round_trip(bus: Any, request_id: UUID, req: QueryRequest) -> dict[str, Any]:
    rid_str = str(request_id)
    ready = asyncio.Event()
    waiter = asyncio.create_task(_wait_for_result(bus, rid_str, ready, _QUERY_TIMEOUT_S))

    try:
        # Wait for the subscriber to be live, then publish.
        try:
            await asyncio.wait_for(ready.wait(), timeout=_SUBSCRIBE_READY_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            waiter.cancel()
            raise HTTPException(status_code=503, detail="subscriber setup timeout") from exc

        await bus.publish(
            f"query.{rid_str}",
            _AdHocQueryRequest(
                question=req.question, request_id=rid_str, site=req.site
            ),
        )

        try:
            return await waiter
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"operator did not respond within {_QUERY_TIMEOUT_S:.0f}s",
            ) from exc
    finally:
        if not waiter.done():
            waiter.cancel()


async def _wait_for_result(
    bus: Any,
    request_id: str,
    ready: asyncio.Event,
    timeout_s: float,
) -> dict[str, Any]:
    """Subscribe to `query.result`, signal `ready`, return matching payload."""
    async def _consume() -> dict[str, Any]:
        iterator = bus.subscribe("query.result").__aiter__()
        # The first event from EventBus.subscribe blocks until psubscribe is
        # ack'd. To signal ready BEFORE we block, we start an inner task
        # that does the first __anext__ — by the time it's running, the
        # psubscribe has been issued.
        first_event_task = asyncio.create_task(iterator.__anext__())
        # Give the event loop one tick so psubscribe runs.
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
    return str(event.get("request_id", "")) == request_id


def _to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    return {}


class _AdHocQueryRequest(BaseModel):
    """Pydantic envelope for the publish step.

    The OperatorAgent's `_extract_request` accepts a dict with
    `question` + `request_id`; `EventBus.publish` calls `model_dump_json()`,
    so this minimal model is enough to satisfy both.
    """

    question: str
    request_id: str
    site: str | None = None

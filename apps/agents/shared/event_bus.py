"""Redis pub/sub wrapper for inter-agent communication.

Purpose:
    Typed publish/subscribe over Redis. Producers never need to know about
    Redis serialization; consumers get Pydantic models back.

Ships: Week 2 (see ROADMAP.md).

Topic conventions live in `events.py::Topic`. See ARCHITECTURE.md § Agent
collaboration for the full topic catalog.

Notes on durability:
    Most topics use Redis pub/sub (fire-and-forget). Lossy on consumer lag,
    which is acceptable for high-volume telemetry. Critical topics —
    `actions.*` and `audit.events` — should use Redis Streams instead.
    Streams support is added in Week 8 when the Executor lands.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import redis.asyncio as redis
from pydantic import BaseModel

from apps.agents.shared.events import BusEvent
from apps.agents.shared.logging import get_logger
from apps.ingestion.schema import TelemetryEvent

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class EventBus:
    """Async Redis pub/sub wrapper.

    Producers call `publish(topic, event)`. Consumers iterate
    `subscribe(pattern)` to receive parsed Pydantic models.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis = redis.from_url(
            url, decode_responses=True, socket_keepalive=True
        )

    # --- factory ---------------------------------------------------------------

    @classmethod
    def from_env(cls) -> EventBus:
        """Construct from the REDIS_URL env var."""
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return cls(url)

    # --- producer --------------------------------------------------------------

    async def publish(self, topic: str, event: BusEvent | TelemetryEvent) -> int:
        """Serialize `event` as JSON and publish to `topic`.

        Returns the number of subscribers that received the message.
        """
        payload = event.model_dump_json()
        n = await self._client.publish(topic, payload)
        log.debug("bus.publish", topic=topic, subscribers=n, event_type=type(event).__name__)
        return int(n)

    # --- consumer --------------------------------------------------------------

    async def subscribe(
        self,
        pattern: str,
        model: type[T] | None = None,
    ) -> AsyncIterator[T | dict[str, Any]]:
        """Subscribe to a topic pattern, yielding parsed events.

        Args:
            pattern: Redis pub/sub pattern, e.g. "telemetry.*" or "incidents.report".
            model: If given, payloads are parsed into this Pydantic class.
                If None, raw dicts are yielded (useful for fan-out routers).
        """
        pubsub = self._client.pubsub()
        await pubsub.psubscribe(pattern)
        log.info("bus.subscribe", pattern=pattern, model=getattr(model, "__name__", None))

        try:
            async for message in pubsub.listen():  # type: ignore[union-attr]
                if message.get("type") not in {"pmessage", "message"}:
                    continue
                try:
                    raw: dict[str, Any] = json.loads(message["data"])
                except json.JSONDecodeError:
                    log.warning("bus.bad_payload", topic=message.get("channel"))
                    continue
                if model is None:
                    yield raw
                else:
                    try:
                        yield model.model_validate(raw)
                    except Exception as exc:  # noqa: BLE001 — bus must never crash on bad payloads
                        log.warning(
                            "bus.parse_failed",
                            topic=message.get("channel"),
                            model=model.__name__,
                            error=str(exc),
                        )
        finally:
            await pubsub.punsubscribe(pattern)
            await pubsub.close()

    # --- lifecycle -------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()


__all__ = ["EventBus"]

"""Base class for long-running agents.

Purpose:
    Boilerplate every agent shares: structlog setup, EventBus connection,
    graceful shutdown on SIGINT/SIGTERM, audit logging helper, periodic
    heartbeat write to Redis. Each agent subclasses `BaseAgent`, declares
    its name + subscribed topics, and implements `handle()`.

Ships: Week 2 (skeleton); Week 4 added heartbeat publish.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.events import BusEvent
from apps.agents.shared.logging import configure_logging, get_logger


class BaseAgent(ABC):
    """Abstract base for every DCOps agent.

    Subclasses must set:
        name (str): Used in logs and the audit trail.
        subscribed_topic (str): The Redis pub/sub pattern this agent listens on.
        event_model (type[BusEvent] | None): If set, payloads are parsed into
            this model before being passed to `handle()`. None means raw dicts.

    Subclasses must implement `handle()`.
    """

    name: str = "agent"
    subscribed_topic: str = ""
    event_model: type[BusEvent] | None = None

    HEARTBEAT_INTERVAL_S = 10.0
    HEARTBEAT_TTL_S = 30  # Redis key TTL so dead agents disappear

    def __init__(self) -> None:
        configure_logging()
        self.log = get_logger(self.name, agent=self.name)
        self.site_id = os.getenv("SITE_ID", "unknown")
        self.bus = EventBus.from_env()
        self._stop = asyncio.Event()
        self._heartbeat_task: asyncio.Task[None] | None = None

    # --- lifecycle -------------------------------------------------------------

    async def on_start(self) -> None:
        """Hook for subclass setup (DB connections, model loading)."""
        self.log.info("agent.start", site_id=self.site_id, topic=self.subscribed_topic)

    async def on_stop(self) -> None:
        """Hook for subclass teardown."""
        await self.bus.close()
        self.log.info("agent.stop")

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                # Windows: signal handlers aren't supported on the proactor loop.
                pass

    # --- main loop -------------------------------------------------------------

    async def serve(self) -> None:
        """Subscribe to `subscribed_topic` and dispatch to `handle()` per event."""
        await self.on_start()
        self._install_signal_handlers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            async for event in self.bus.subscribe(self.subscribed_topic, self.event_model):
                if self._stop.is_set():
                    break
                try:
                    await self.handle(event)
                except Exception as exc:  # noqa: BLE001 — never let a bad event kill the agent
                    self.log.exception("agent.handle_failed", error=str(exc))
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await self.on_stop()

    # --- heartbeat -------------------------------------------------------------

    @classmethod
    def heartbeat_key(cls, site_id: str, agent_name: str) -> str:
        return f"agent:{site_id}:{agent_name}:heartbeat"

    async def _heartbeat_loop(self) -> None:
        """Write a heartbeat record to Redis every `HEARTBEAT_INTERVAL_S`.

        Key: `agent:<site>:<name>:heartbeat`, TTL = 3× the publish interval
        so the key drops if the agent dies. Value is a small JSON blob
        with `last_seen_ts` and `pid` so the dashboard can show liveness.
        """
        key = self.heartbeat_key(self.site_id, self.name)
        while not self._stop.is_set():
            payload = json.dumps(
                {
                    "agent": self.name,
                    "site_id": self.site_id,
                    "last_seen_ts": time.time(),
                    "pid": os.getpid(),
                }
            )
            try:
                # `bus._client` is the underlying redis.asyncio client.
                client = getattr(self.bus, "_client", None)
                if client is not None:
                    await client.set(key, payload, ex=self.HEARTBEAT_TTL_S)
            except Exception as exc:  # noqa: BLE001 — heartbeat failures don't kill the agent
                self.log.debug("agent.heartbeat_failed", error=str(exc))
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL_S)
            except asyncio.CancelledError:
                raise

    # --- subclass contract -----------------------------------------------------

    @abstractmethod
    async def handle(self, event: BusEvent | dict[str, Any]) -> None:
        """Process one bus event. Subclasses must implement."""
        ...

    # --- helpers ---------------------------------------------------------------

    async def publish(self, topic: str, event: BusEvent) -> None:
        await self.bus.publish(topic, event)

    async def audit(self, **fields: Any) -> None:
        """Emit an audit-level log record. TODO(week-3): also push to audit.events stream."""
        self.log.info("agent.audit", **fields)

    @classmethod
    def run(cls) -> None:
        """Entry point used by every agent's `if __name__ == "__main__":` block."""
        agent = cls()
        try:
            asyncio.run(agent.serve())
        except KeyboardInterrupt:
            pass


__all__ = ["BaseAgent", "BaseModel"]

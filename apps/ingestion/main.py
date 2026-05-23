"""Telemetry ingestion service entry point.

Two long-running responsibilities:

  1. **Source pollers** — one task per normalizer (`redfish`, `dcgm`, `ipmi`,
     `snmp`, `env`). Each calls its `poll()` async generator on a fixed
     cadence and publishes `TelemetryEvent` records to the Redis bus.

  2. **TimescaleDB writer** — subscribes to `telemetry.*` (which receives
     events from BOTH the source pollers and the simulator) and bulk-inserts
     into the `telemetry` hypertable. Batches by count or by interval, so
     the >100K-rows-in-5-min success criterion is achievable without
     row-by-row INSERT overhead.

Dependencies:
    apps/ingestion/schema.py        — TelemetryEvent
    apps/agents/shared/event_bus.py — Redis publish + subscribe
    apps/agents/shared/ts_client.py — TimescaleStore.insert_telemetry
    apps/ingestion/normalizers/     — per-source adapters
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.logging import configure_logging, get_logger
from apps.agents.shared.ts_client import TimescaleStore
from apps.ingestion.normalizers import dcgm, env, ipmi, redfish, snmp
from apps.ingestion.schema import TelemetryEvent

log = get_logger(__name__)

# Source poll cadence (seconds). Per-source overrides are read from env.
DEFAULT_POLL_SEC = 5.0
# Writer batching. Flush whenever we have FLUSH_MAX events OR FLUSH_INTERVAL_S elapsed.
WRITER_FLUSH_MAX = int(os.getenv("INGEST_WRITER_FLUSH_MAX", "500"))
WRITER_FLUSH_INTERVAL_S = float(os.getenv("INGEST_WRITER_FLUSH_INTERVAL_S", "2.0"))


PollFn = Callable[[], AsyncIterator[TelemetryEvent]]


async def run_source(name: str, poll_fn: PollFn, bus: EventBus, interval: float) -> None:
    """Generic poller loop. Each normalizer exposes an async `poll()` generator."""
    log.info("ingestion.source.start", source=name, interval=interval)
    while True:
        n_emitted = 0
        try:
            async for event in poll_fn():
                topic = f"telemetry.{name}.{event.device_type.value}"
                await bus.publish(topic, event)
                n_emitted += 1
        except Exception as exc:  # noqa: BLE001 — never let one bad source kill the service
            log.exception("ingestion.source.error", source=name, error=str(exc))
        if n_emitted:
            log.debug("ingestion.source.cycle", source=name, emitted=n_emitted)
        await asyncio.sleep(interval)


async def run_writer(bus: EventBus, ts: TimescaleStore) -> None:
    """Subscribe to telemetry.* and bulk-insert into the TimescaleDB hypertable.

    Batches up to `WRITER_FLUSH_MAX` events or `WRITER_FLUSH_INTERVAL_S`
    seconds (whichever first). On Timescale outage, the in-memory batch is
    dropped after one failed flush — telemetry loss is acceptable per the
    architecture (see ARCHITECTURE.md § Failure modes); the bus still
    delivered to subscribers.
    """
    if not ts.enabled:
        log.warning("ingestion.writer.disabled", reason="ts.connect() failed")
        return

    log.info(
        "ingestion.writer.start",
        flush_max=WRITER_FLUSH_MAX,
        flush_interval_s=WRITER_FLUSH_INTERVAL_S,
    )

    batch: list[dict[str, Any]] = []
    last_flush = asyncio.get_event_loop().time()

    async def _flush(reason: str) -> None:
        nonlocal batch, last_flush
        if not batch:
            return
        n = await ts.insert_telemetry(batch)
        log.info("ingestion.writer.flushed", n=n, attempted=len(batch), reason=reason)
        batch = []
        last_flush = asyncio.get_event_loop().time()

    async def _consume() -> None:
        async for event in bus.subscribe("telemetry.*"):
            if isinstance(event, dict):
                batch.append(event)
            else:
                # bus.subscribe(model=None) yields dicts; defensive copy if not.
                batch.append(event if isinstance(event, dict) else dict(event))
            if len(batch) >= WRITER_FLUSH_MAX:
                await _flush(reason="size")

    async def _ticker() -> None:
        while True:
            await asyncio.sleep(WRITER_FLUSH_INTERVAL_S)
            elapsed = asyncio.get_event_loop().time() - last_flush
            if batch and elapsed >= WRITER_FLUSH_INTERVAL_S:
                await _flush(reason="interval")

    try:
        await asyncio.gather(_consume(), _ticker())
    except Exception as exc:  # noqa: BLE001
        log.exception("ingestion.writer.crashed", error=str(exc))
    finally:
        await _flush(reason="shutdown")


async def main() -> None:
    configure_logging()
    site = os.getenv("SITE_ID", "unknown")
    log.info("ingestion.start", site_id=site)

    bus = EventBus.from_env()
    ts = TimescaleStore.from_env()
    await ts.connect()

    # Normalizer sources. In dev the simulator publishes directly to the bus;
    # these become the real data path once `--profile mocks` (or real hardware)
    # is up. Each `poll()` is a no-op when the configured endpoint is missing.
    sources: list[tuple[str, PollFn, float]] = [
        ("redfish", redfish.poll, float(os.getenv("REDFISH_INTERVAL_SEC", "30"))),
        ("dcgm",    dcgm.poll,    float(os.getenv("DCGM_INTERVAL_SEC", "5"))),
        ("ipmi",    ipmi.poll,    float(os.getenv("IPMI_INTERVAL_SEC", "30"))),
        ("snmp",    snmp.poll,    float(os.getenv("SNMP_INTERVAL_SEC", "15"))),
        ("env",     env.poll,     float(os.getenv("ENV_INTERVAL_SEC", "10"))),
    ]

    tasks = [asyncio.create_task(run_source(n, fn, bus, i)) for n, fn, i in sources]
    tasks.append(asyncio.create_task(run_writer(bus, ts)))

    try:
        await asyncio.gather(*tasks)
    finally:
        await ts.close()


if __name__ == "__main__":
    asyncio.run(main())

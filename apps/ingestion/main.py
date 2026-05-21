"""Telemetry ingestion service entry point.

Purpose:
    Long-running process that pulls from configured telemetry sources via
    the per-source normalizers and publishes normalized `TelemetryEvent`s
    to the Redis bus. Also writes a copy to TimescaleDB for query-time use.

Ships: Week 2 (skeleton); real source pollers in Weeks 2-3.

Dependencies:
    apps/ingestion/schema.py       — TelemetryEvent
    apps/agents/shared/event_bus.py — Redis publish
    apps/ingestion/normalizers/    — per-source adapters
"""

from __future__ import annotations

import asyncio
import os

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.logging import configure_logging, get_logger
from apps.ingestion.normalizers import dcgm, env, ipmi, redfish, snmp

log = get_logger(__name__)

# Source poll cadence (seconds). Per-source overrides are read from env.
DEFAULT_POLL_SEC = 5.0


async def run_source(name: str, poll_fn, bus: EventBus, interval: float) -> None:
    """Generic poller loop. Each normalizer exposes an async `poll()` generator."""
    log.info("ingestion.source.start", source=name, interval=interval)
    while True:
        try:
            async for event in poll_fn():
                topic = f"telemetry.{name}.{event.device_type.value}"
                await bus.publish(topic, event)
        except Exception as exc:  # noqa: BLE001 — never let one bad source kill the service
            log.exception("ingestion.source.error", source=name, error=str(exc))
        await asyncio.sleep(interval)


async def main() -> None:
    configure_logging()
    site = os.getenv("SITE_ID", "unknown")
    log.info("ingestion.start", site_id=site)
    bus = EventBus.from_env()

    # TODO(week-2): in dev, the simulator publishes directly. Real source
    # pollers below are stubs that yield nothing until enabled.
    sources = [
        ("redfish", redfish.poll, float(os.getenv("REDFISH_INTERVAL_SEC", "30"))),
        ("dcgm",    dcgm.poll,    float(os.getenv("DCGM_INTERVAL_SEC", "5"))),
        ("ipmi",    ipmi.poll,    float(os.getenv("IPMI_INTERVAL_SEC", "30"))),
        ("snmp",    snmp.poll,    float(os.getenv("SNMP_INTERVAL_SEC", "15"))),
        ("env",     env.poll,     float(os.getenv("ENV_INTERVAL_SEC", "10"))),
    ]
    await asyncio.gather(*[run_source(n, fn, bus, i) for n, fn, i in sources])


if __name__ == "__main__":
    asyncio.run(main())

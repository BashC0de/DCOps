"""Environmental sensor + CRAC normalizer.

Purpose:
    Aggregates inlet/outlet temperature, humidity, and CRAC supply/return
    metrics from facility sensors (typically over Modbus or BACnet via a
    gateway exposing HTTP/JSON).

Ships: Week 2 (stub); real wiring Week 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from apps.ingestion.schema import TelemetryEvent


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Yield environmental + CRAC telemetry events. No-op until Week 3."""
    # TODO(week-3): adapter for a Modbus/BACnet gateway in front of facility sensors.
    if False:
        yield None  # type: ignore[misc]
    return

"""IPMI normalizer.

Purpose:
    IPMI over LAN sensor table + System Event Log (SEL) parser. Converts
    fan, temperature, voltage, and PSU readings to TelemetryEvent records.

Ships: Week 2 (stub); real IPMI integration deferred (out of v1.0 scope).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from apps.ingestion.schema import TelemetryEvent


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Yield IPMI-sourced telemetry events. No-op until enabled."""
    # TODO(week-3+): use ipmitool subprocess or pyghmi for in-process IPMI.
    if False:
        yield None  # type: ignore[misc]
    return

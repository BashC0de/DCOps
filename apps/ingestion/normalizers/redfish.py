"""Redfish (Dell iDRAC) normalizer.

Purpose:
    Polls Dell iDRAC `/redfish/v1/Systems/{id}` and converts the response
    into `TelemetryEvent` records using the canonical metric catalog.

Ships: Week 2 (stub); real HTTP polling Week 3.

In dev/demo mode, the simulator publishes directly to the bus; this
normalizer yields nothing until pointed at real hardware.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from apps.ingestion.schema import TelemetryEvent


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Yield Redfish-sourced telemetry events. No-op until Week 3."""
    # TODO(week-3): real iDRAC client; httpx with cert pinning + auth.
    if False:
        yield None  # type: ignore[misc]  # placeholder to make this a generator
    return

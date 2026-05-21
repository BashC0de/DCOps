"""SNMP normalizer for switches and PDUs.

Purpose:
    Polls SNMP OIDs for switch port stats and PDU load. Targets the most
    common vendor MIBs (Cisco, Arista, APC, Schneider).

Ships: Week 2 (stub); real SNMP wiring Week 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from apps.ingestion.schema import TelemetryEvent


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Yield SNMP-sourced telemetry events. No-op until Week 3."""
    # TODO(week-3): use pysnmp.hlapi.asyncio for non-blocking SNMP GET bulk.
    if False:
        yield None  # type: ignore[misc]
    return

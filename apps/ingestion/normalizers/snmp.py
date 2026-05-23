"""SNMP normalizer for switches and PDUs.

Polls a JSON SNMP-walk adapter (the in-repo mocks service exposes one at
`/snmp/walk`). Against real hardware this would use `pysnmp.hlapi.asyncio`
to GET-BULK from the device; the JSON adapter is the shape our code talks.

Translates a small set of well-known OIDs to canonical metrics:
    ifInOctets, ifOutOctets, ifInErrors  → net.bps.in / out / err.in
    ifOperStatus                          → net.port.up
    rPDU2PhaseStatusLoadState             → pdu.load.percent

Ships: Week 2 (real polling against the mocks profile).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from apps.agents.shared.logging import get_logger
from apps.ingestion.normalizers._http import base_url, get_json
from apps.ingestion.schema import CanonicalMetric, DeviceType, Severity, TelemetryEvent

log = get_logger(__name__)


def _root() -> str | None:
    explicit = os.getenv("SNMP_BASE_URL")
    if explicit:
        return explicit
    bu = base_url()
    return f"{bu}/snmp/walk" if bu else None


def _site() -> str:
    return os.getenv("SITE_ID", "unknown")


def _hall_rack(device_id: str) -> tuple[str, str]:
    parts = device_id.split("-")
    if len(parts) >= 4 and parts[1].startswith("h") and parts[2].startswith("r"):
        return f"{parts[0]}-{parts[1]}", f"{parts[0]}-{parts[1]}-{parts[2]}"
    return "unknown", "unknown"


async def poll() -> AsyncIterator[TelemetryEvent]:
    url = _root()
    if not url:
        return
    payload = await get_json(url)
    if not payload:
        return

    site = _site()
    for entry in payload.get("devices", []):
        device_id = entry.get("device_id")
        if not isinstance(device_id, str):
            continue
        hall_id, rack_id = _hall_rack(device_id)
        dtype = entry.get("device_type", "switch")
        oids = entry.get("oids", {}) or {}

        if dtype == "switch":
            bps_in = oids.get("ifInOctets.1")
            if isinstance(bps_in, (int, float)):
                yield TelemetryEvent(
                    site_id=site, hall_id=hall_id, rack_id=rack_id,
                    device_id=device_id, device_type=DeviceType.SWITCH,
                    metric=CanonicalMetric.NET_BPS_IN, value=float(bps_in),
                    unit="bps", severity=Severity.INFO,
                    metadata={"source": "snmp", "oid": "ifInOctets.1"},
                )
            bps_out = oids.get("ifOutOctets.1")
            if isinstance(bps_out, (int, float)):
                yield TelemetryEvent(
                    site_id=site, hall_id=hall_id, rack_id=rack_id,
                    device_id=device_id, device_type=DeviceType.SWITCH,
                    metric=CanonicalMetric.NET_BPS_OUT, value=float(bps_out),
                    unit="bps", severity=Severity.INFO,
                    metadata={"source": "snmp", "oid": "ifOutOctets.1"},
                )
            errs_in = oids.get("ifInErrors.1")
            if isinstance(errs_in, (int, float)):
                yield TelemetryEvent(
                    site_id=site, hall_id=hall_id, rack_id=rack_id,
                    device_id=device_id, device_type=DeviceType.SWITCH,
                    metric=CanonicalMetric.NET_ERR_IN, value=float(errs_in),
                    unit="count", severity=Severity.INFO,
                    metadata={"source": "snmp", "oid": "ifInErrors.1"},
                )
            port_up = oids.get("ifOperStatus.1")
            if isinstance(port_up, (int, float)):
                yield TelemetryEvent(
                    site_id=site, hall_id=hall_id, rack_id=rack_id,
                    device_id=device_id, device_type=DeviceType.SWITCH,
                    metric=CanonicalMetric.NET_PORT_UP,
                    value=1.0 if int(port_up) == 1 else 0.0,
                    unit=None,
                    severity=Severity.INFO if int(port_up) == 1 else Severity.ERROR,
                    metadata={"source": "snmp", "oid": "ifOperStatus.1"},
                )
        elif dtype == "pdu":
            load = oids.get("rPDU2PhaseStatusLoadState.1")
            if isinstance(load, (int, float)):
                yield TelemetryEvent(
                    site_id=site, hall_id=hall_id, rack_id=rack_id,
                    device_id=device_id, device_type=DeviceType.PDU,
                    metric=CanonicalMetric.PDU_LOAD_PERCENT,
                    value=float(load), unit="percent",
                    severity=Severity.INFO,
                    metadata={"source": "snmp", "oid": "rPDU2PhaseStatusLoadState.1"},
                )

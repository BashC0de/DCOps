"""Redfish (Dell iDRAC) normalizer.

Polls `/redfish/v1/Systems`, then for each system polls Thermal + Power
sub-resources and converts the readings into `TelemetryEvent` records
keyed on the `CanonicalMetric` catalog.

In dev, points at the in-repo `apps.mocks` service (set
`MOCKS_BASE_URL=http://mocks:8090`). Against real Dell hardware, point
`REDFISH_BASE_URL` at the iDRAC root.

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
    return os.getenv("REDFISH_BASE_URL") or base_url()


def _site() -> str:
    return os.getenv("SITE_ID", "unknown")


def _hall_rack(device_id: str) -> tuple[str, str]:
    """Recover hall + rack from a device ID like `frankfurt-h1-r07-srv03`.

    Returns ("unknown", "unknown") if the ID doesn't follow that convention.
    """
    parts = device_id.split("-")
    # site-h<H>-r<RR>-srv<SS> or similar
    if len(parts) >= 4 and parts[1].startswith("h") and parts[2].startswith("r"):
        return f"{parts[0]}-{parts[1]}", f"{parts[0]}-{parts[1]}-{parts[2]}"
    return "unknown", "unknown"


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Poll the configured Redfish endpoint and emit one TelemetryEvent per metric."""
    root = _root()
    if not root:
        return

    site = _site()
    listing = await get_json(f"{root}/redfish/v1/Systems")
    if not listing:
        return

    for member in listing.get("Members", []):
        oid = member.get("@odata.id")
        if not isinstance(oid, str):
            continue
        # Device ID is the last path segment of /redfish/v1/Systems/{id}.
        device_id = oid.rstrip("/").rsplit("/", 1)[-1]
        hall_id, rack_id = _hall_rack(device_id)

        thermal = await get_json(f"{root}/redfish/v1/Chassis/{device_id}/Thermal")
        if thermal:
            for t in thermal.get("Temperatures", []):
                value = t.get("ReadingCelsius")
                name = t.get("Name", "")
                if not isinstance(value, (int, float)):
                    continue
                if "CPU" in name:
                    metric = CanonicalMetric.CPU_TEMP_CELSIUS
                elif "Inlet" in name or t.get("PhysicalContext") == "Intake":
                    metric = CanonicalMetric.ENV_INLET_CELSIUS
                elif "Outlet" in name or t.get("PhysicalContext") == "Exhaust":
                    metric = CanonicalMetric.ENV_OUTLET_CELSIUS
                else:
                    continue
                yield TelemetryEvent(
                    site_id=site,
                    hall_id=hall_id,
                    rack_id=rack_id,
                    device_id=device_id,
                    device_type=DeviceType.SERVER,
                    metric=metric,
                    value=float(value),
                    unit="celsius",
                    severity=_severity_from_redfish(t.get("Status", {})),
                    metadata={"sensor": name, "source": "redfish"},
                )
            for f in thermal.get("Fans", []):
                rpm = f.get("Reading")
                if not isinstance(rpm, (int, float)):
                    continue
                yield TelemetryEvent(
                    site_id=site,
                    hall_id=hall_id,
                    rack_id=rack_id,
                    device_id=device_id,
                    device_type=DeviceType.SERVER,
                    metric=CanonicalMetric.FAN_RPM,
                    value=float(rpm),
                    unit="RPM",
                    severity=_severity_from_redfish(f.get("Status", {})),
                    metadata={"sensor": f.get("Name", ""), "source": "redfish"},
                )

        power = await get_json(f"{root}/redfish/v1/Chassis/{device_id}/Power")
        if power:
            for pc in power.get("PowerControl", []):
                watts = pc.get("PowerConsumedWatts")
                if isinstance(watts, (int, float)):
                    yield TelemetryEvent(
                        site_id=site,
                        hall_id=hall_id,
                        rack_id=rack_id,
                        device_id=device_id,
                        device_type=DeviceType.SERVER,
                        metric=CanonicalMetric.POWER_DRAW_WATTS,
                        value=float(watts),
                        unit="watts",
                        severity=Severity.INFO,
                        metadata={"source": "redfish"},
                    )
            for ps in power.get("PowerSupplies", []):
                eff = ps.get("EfficiencyPercent")
                if isinstance(eff, (int, float)):
                    yield TelemetryEvent(
                        site_id=site,
                        hall_id=hall_id,
                        rack_id=rack_id,
                        device_id=device_id,
                        device_type=DeviceType.SERVER,
                        metric=CanonicalMetric.PSU_EFFICIENCY_PERCENT,
                        value=float(eff),
                        unit="percent",
                        severity=_severity_from_redfish(ps.get("Status", {})),
                        metadata={"sensor": ps.get("Name", ""), "source": "redfish"},
                    )


def _severity_from_redfish(status: dict) -> Severity:
    health = (status or {}).get("Health", "OK")
    if health == "Critical":
        return Severity.CRITICAL
    if health == "Warning":
        return Severity.WARN
    return Severity.INFO

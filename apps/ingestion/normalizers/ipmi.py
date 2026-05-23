"""IPMI normalizer.

Polls a JSON IPMI-sensor endpoint (the in-repo mocks service emulates
this) and emits canonical telemetry. Against real hardware, this would
shell out to `ipmitool` or use `pyghmi`; for the demo we keep the same
TelemetryEvent shape against a JSON adapter.

Ships: Week 2 (real polling against the mocks profile).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from apps.agents.shared.logging import get_logger
from apps.ingestion.normalizers._http import base_url, get_json
from apps.ingestion.schema import CanonicalMetric, DeviceType, Severity, TelemetryEvent

log = get_logger(__name__)

# Mock's sensor `metric` field → canonical metric.
_METRIC_MAP: dict[str, CanonicalMetric] = {
    "cpu.temp.celsius":          CanonicalMetric.CPU_TEMP_CELSIUS,
    "fan.rpm":                   CanonicalMetric.FAN_RPM,
    "power.draw.watts":          CanonicalMetric.POWER_DRAW_WATTS,
    "psu.efficiency.percent":    CanonicalMetric.PSU_EFFICIENCY_PERCENT,
}


def _root() -> str | None:
    explicit = os.getenv("IPMI_BASE_URL")
    if explicit:
        return explicit
    bu = base_url()
    return f"{bu}/ipmi/sensors" if bu else None


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
        for sensor in entry.get("sensors", []):
            canonical = _METRIC_MAP.get(sensor.get("metric"))
            value = sensor.get("value")
            if canonical is None or not isinstance(value, (int, float)):
                continue
            yield TelemetryEvent(
                site_id=site,
                hall_id=hall_id,
                rack_id=rack_id,
                device_id=device_id,
                device_type=DeviceType.SERVER,
                metric=canonical,
                value=float(value),
                unit=sensor.get("unit"),
                severity=Severity.INFO,
                metadata={"source": "ipmi", "sensor_name": sensor.get("name", "")},
            )

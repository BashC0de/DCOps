"""Environmental + CRAC normalizer.

Polls a JSON adapter for facility sensors (the mocks service exposes one
at `/env/sensors`). Each sensor entry already carries a canonical metric
name, so this normalizer is mostly a passthrough into TelemetryEvent.

Against real facilities this adapter would sit in front of a
Modbus/BACnet gateway or a building-management system.

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
    explicit = os.getenv("ENV_BASE_URL")
    if explicit:
        return explicit
    bu = base_url()
    return f"{bu}/env/sensors" if bu else None


def _site() -> str:
    return os.getenv("SITE_ID", "unknown")


async def poll() -> AsyncIterator[TelemetryEvent]:
    url = _root()
    if not url:
        return
    payload = await get_json(url)
    if not payload:
        return

    site = _site()
    canonical_values = {m.value for m in CanonicalMetric}

    for sensor in payload.get("sensors", []):
        metric_name = sensor.get("metric")
        value = sensor.get("value")
        if metric_name not in canonical_values or not isinstance(value, (int, float)):
            continue
        device_id = sensor.get("device_id") or sensor.get("location") or "env-unknown"
        device_type_raw = sensor.get("device_type", "sensor")
        try:
            device_type = DeviceType(device_type_raw)
        except ValueError:
            device_type = DeviceType.SENSOR

        yield TelemetryEvent(
            site_id=site,
            hall_id=sensor.get("hall_id") or "unknown",
            rack_id=sensor.get("rack_id") or "unknown",
            device_id=device_id,
            device_type=device_type,
            metric=CanonicalMetric(metric_name),
            value=float(value),
            unit=sensor.get("unit"),
            severity=Severity.INFO,
            metadata={"source": "env"},
        )

"""Universal telemetry schema.

Purpose:
    The `TelemetryEvent` Pydantic model defined here is the single, canonical
    payload that every component in DCOps Copilot reads and writes. Normalizers,
    agents, the event bus, the simulator, and the API all speak this language.
    No raw vendor payloads cross module boundaries.

Ships: Week 2 (see ROADMAP.md).

Depended on by:
    - apps/ingestion/main.py and every normalizer in apps/ingestion/normalizers/
    - apps/agents/shared/event_bus.py (typed publish/subscribe wrappers)
    - apps/simulator/*  (emits these directly)
    - apps/api/routes/telemetry.py
    - apps/agents/* (all eight subscribe to events of this shape)

Conventions:
    Metric names follow `<component>.<dimension>.<aspect>`, e.g.
    `gpu.ecc.uncorrectable`, `power.draw.watts`. The full catalog lives in
    `CANONICAL_METRICS` below — adding a metric means adding it here so typos
    fail at parse time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceType(StrEnum):
    """The kinds of devices our telemetry pipeline understands."""

    SERVER = "server"
    GPU = "gpu"
    SWITCH = "switch"
    PDU = "pdu"
    CRAC = "crac"
    SENSOR = "sensor"


class Severity(StrEnum):
    """Event severity. Used by Sentinel for routing and by the dashboard for coloring."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


class CanonicalMetric(StrEnum):
    """Frozen catalog of metric names. Add new metrics here, not as strings elsewhere."""

    # --- CPU / system ---
    CPU_TEMP_CELSIUS = "cpu.temp.celsius"
    CPU_UTIL_PERCENT = "cpu.util.percent"
    MEM_USED_BYTES = "mem.used.bytes"
    MEM_ECC_CORRECTABLE = "mem.ecc.correctable"
    MEM_ECC_UNCORRECTABLE = "mem.ecc.uncorrectable"

    # --- GPU ---
    GPU_TEMP_CELSIUS = "gpu.temp.celsius"
    GPU_UTIL_PERCENT = "gpu.util.percent"
    GPU_MEM_USED_BYTES = "gpu.mem.used.bytes"
    GPU_POWER_WATTS = "gpu.power.watts"
    GPU_ECC_CORRECTABLE = "gpu.ecc.correctable"
    GPU_ECC_UNCORRECTABLE = "gpu.ecc.uncorrectable"
    GPU_XID_CODE = "gpu.xid.code"

    # --- Power ---
    POWER_DRAW_WATTS = "power.draw.watts"
    PSU_EFFICIENCY_PERCENT = "psu.efficiency.percent"
    PDU_LOAD_PERCENT = "pdu.load.percent"

    # --- Cooling / environment ---
    FAN_RPM = "fan.rpm"
    ENV_INLET_CELSIUS = "env.inlet.celsius"
    ENV_OUTLET_CELSIUS = "env.outlet.celsius"
    ENV_HUMIDITY_PERCENT = "env.humidity.percent"
    CRAC_SUPPLY_CELSIUS = "crac.supply.celsius"
    CRAC_RETURN_CELSIUS = "crac.return.celsius"
    CRAC_FAN_PERCENT = "crac.fan.percent"

    # --- Storage / SMART ---
    DISK_REALLOCATED_SECTORS = "disk.reallocated.sectors"
    DISK_PENDING_SECTORS = "disk.pending.sectors"
    DISK_TEMP_CELSIUS = "disk.temp.celsius"

    # --- Network / switch ---
    NET_BPS_IN = "net.bps.in"
    NET_BPS_OUT = "net.bps.out"
    NET_ERR_IN = "net.err.in"
    NET_PORT_UP = "net.port.up"


class TelemetryEvent(BaseModel):
    """A single telemetry sample, normalized.

    Every field except `metadata` is mandatory. `metadata` carries
    source-specific extras (XID codes, sensor IDs, polling source) that
    don't fit the universal shape.
    """

    model_config = ConfigDict(
        frozen=True,                     # immutability prevents accidental mutation downstream
        extra="forbid",                  # surface typos in producers immediately
        ser_json_timedelta="iso8601",
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp; microsecond precision recommended.",
    )
    site_id: str = Field(..., min_length=1, description="Site identifier, e.g. 'frankfurt'.")
    hall_id: str = Field(..., min_length=1, description="Hall identifier, e.g. 'fra-h1'.")
    rack_id: str = Field(..., min_length=1, description="Rack identifier, e.g. 'fra-h1-r07'.")
    device_id: str = Field(..., min_length=1, description="Device identifier.")
    device_type: DeviceType
    metric: CanonicalMetric
    value: float | int | str
    unit: str | None = None
    severity: Severity = Severity.INFO
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC).")
        return v.astimezone(timezone.utc)


__all__ = [
    "CanonicalMetric",
    "DeviceType",
    "Severity",
    "TelemetryEvent",
]

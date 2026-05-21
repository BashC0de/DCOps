"""Physics-engine entity classes.

Purpose:
    Dataclass models for everything that exists in the simulated data hall:
    sites, halls, racks, servers, GPUs, switches, PDUs, CRAC units. These
    are shared by `apps.simulator` (instantiates them) and `apps.physics`
    (mutates them via thermal/power/failure models).

Ships: Week 1 (skeletons); thermal/power state evolution Week 3.

Design note:
    These are pure-Python dataclasses, not Pydantic models. They're hot —
    mutated thousands of times per simulated tick — and we don't need
    validation overhead at that frequency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class DeviceState(StrEnum):
    """High-level lifecycle state of a device."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    FAILED = "failed"
    OFFLINE = "offline"


class FailureMode(StrEnum):
    """Programmatic failure modes that the injector can apply.

    Adding a new mode here means updating apps/physics/failure_injector.py to
    define its physical effects.
    """

    NONE = "none"
    GPU_ECC_RUNAWAY = "gpu_ecc_runaway"
    GPU_THERMAL_THROTTLE = "gpu_thermal_throttle"
    GPU_XID_43 = "gpu_xid_43"
    PSU_EFFICIENCY_DRIFT = "psu_efficiency_drift"
    PSU_FAIL = "psu_fail"
    FAN_STUCK = "fan_stuck"
    CRAC_FAIL = "crac_fail"
    SWITCH_PORT_FLAP = "switch_port_flap"
    DISK_REALLOC_RAMP = "disk_realloc_ramp"
    NIC_PACKET_LOSS = "nic_packet_loss"


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@dataclass
class Device:
    """Base device. Subclassed by Server, GPU, Switch, PDU, CRACUnit."""

    id: str
    type: Literal["server", "gpu", "switch", "pdu", "crac"]
    model: str
    vendor: str
    rack_id: str
    state: DeviceState = DeviceState.HEALTHY
    failure_mode: FailureMode = FailureMode.NONE
    inlet_temp_c: float = 22.0
    outlet_temp_c: float = 30.0
    power_draw_w: float = 0.0
    metadata: dict[str, float | str] = field(default_factory=dict)


@dataclass
class Server(Device):
    type: Literal["server"] = "server"
    cpu_util_percent: float = 30.0
    cpu_temp_c: float = 55.0
    mem_used_bytes: int = 0
    mem_total_bytes: int = 256 * 1024**3
    fan_rpm: int = 5000
    psu_efficiency_percent: float = 94.0
    rated_power_w: float = 800.0


@dataclass
class GPU(Device):
    type: Literal["gpu"] = "gpu"
    parent_server_id: str = ""
    gpu_temp_c: float = 65.0
    gpu_util_percent: float = 70.0
    gpu_mem_used_bytes: int = 0
    gpu_mem_total_bytes: int = 80 * 1024**3
    ecc_correctable_count: int = 0
    ecc_uncorrectable_count: int = 0
    last_xid_code: int | None = None
    rated_power_w: float = 700.0


@dataclass
class Switch(Device):
    type: Literal["switch"] = "switch"
    port_count: int = 48
    port_up_count: int = 48
    bps_in: int = 0
    bps_out: int = 0
    err_in_count: int = 0
    rated_power_w: float = 250.0


@dataclass
class PDU(Device):
    type: Literal["pdu"] = "pdu"
    load_percent: float = 50.0
    capacity_w: float = 15_000.0
    powered_device_ids: list[str] = field(default_factory=list)


@dataclass
class CRACUnit(Device):
    type: Literal["crac"] = "crac"
    hall_id_serves: str = ""
    supply_temp_c: float = 18.0
    return_temp_c: float = 27.0
    fan_percent: float = 60.0
    capacity_kw: float = 50.0
    rated_power_w: float = 8_000.0


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

@dataclass
class Rack:
    """One rack in a hall."""

    id: str
    hall_id: str
    position: tuple[int, int]            # (row, column) on hall floor
    capacity_u: int = 42
    devices: list[Device] = field(default_factory=list)


@dataclass
class DataHall:
    """A single hall in a site. Has its own thermal zone + CRAC units."""

    id: str
    site_id: str
    capacity_kw: float
    racks: list[Rack] = field(default_factory=list)
    crac_units: list[CRACUnit] = field(default_factory=list)
    ambient_inlet_c: float = 22.0       # set point for cold aisle

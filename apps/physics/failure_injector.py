"""Programmatic failure injection API.

Purpose:
    Maps a `FailureMode` enum value to a side-effecting function that
    mutates the relevant device state. The simulator + the `inject_failure`
    CLI both go through this single API so demo scenarios and benchmark
    runs are bit-for-bit reproducible.

Ships: Week 3 (full impl); Week 1 lays down the contract.

Usage:
    inject(hall, device_id="fra-h1-r07-gpu03", mode=FailureMode.GPU_ECC_RUNAWAY)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from apps.agents.shared.logging import get_logger
from apps.physics.entities import (
    CRACUnit,
    DataHall,
    Device,
    DeviceState,
    FailureMode,
    GPU,
    PDU,
    Server,
    Switch,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inject(hall: DataHall, device_id: str, mode: FailureMode) -> Device:
    """Apply `mode` to the device with the given id in the hall."""
    device = _find_device(hall, device_id)
    if device is None:
        raise LookupError(f"Device {device_id} not found in hall {hall.id}")

    handler = _HANDLERS.get(mode)
    if handler is None:
        raise NotImplementedError(f"No injector handler for {mode}")

    handler(device, hall)
    device.failure_mode = mode
    log.info("physics.inject", device_id=device_id, mode=mode, state=device.state)
    return device


def clear(hall: DataHall, device_id: str) -> Device:
    """Reset a device back to HEALTHY / FailureMode.NONE."""
    device = _find_device(hall, device_id)
    if device is None:
        raise LookupError(f"Device {device_id} not found in hall {hall.id}")
    device.state = DeviceState.HEALTHY
    device.failure_mode = FailureMode.NONE
    log.info("physics.inject.clear", device_id=device_id)
    return device


# ---------------------------------------------------------------------------
# Per-mode handlers
# ---------------------------------------------------------------------------

def _find_device(hall: DataHall, device_id: str) -> Device | None:
    for rack in hall.racks:
        for d in rack.devices:
            if d.id == device_id:
                return d
    for c in hall.crac_units:
        if c.id == device_id:
            return cast(Device, c)
    return None


def _gpu_ecc_runaway(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, GPU):
        raise TypeError("GPU_ECC_RUNAWAY requires a GPU device")
    d.state = DeviceState.FAILING
    d.ecc_correctable_count += 50_000        # large spike
    d.ecc_uncorrectable_count += 5
    d.gpu_temp_c += 8.0


def _gpu_thermal_throttle(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, GPU):
        raise TypeError("GPU_THERMAL_THROTTLE requires a GPU device")
    d.state = DeviceState.DEGRADED
    d.gpu_temp_c = 92.0
    d.gpu_util_percent = max(0.0, d.gpu_util_percent - 30.0)


def _gpu_xid_43(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, GPU):
        raise TypeError("GPU_XID_43 requires a GPU device")
    d.state = DeviceState.FAILING
    d.last_xid_code = 43


def _psu_efficiency_drift(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Server):
        raise TypeError("PSU_EFFICIENCY_DRIFT requires a Server device")
    d.state = DeviceState.DEGRADED
    d.psu_efficiency_percent = max(70.0, d.psu_efficiency_percent - 12.0)


def _psu_fail(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Server):
        raise TypeError("PSU_FAIL requires a Server device")
    d.state = DeviceState.FAILED
    d.power_draw_w = 0.0


def _fan_stuck(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Server):
        raise TypeError("FAN_STUCK requires a Server device")
    d.state = DeviceState.DEGRADED
    d.fan_rpm = 0
    d.cpu_temp_c += 12.0


def _crac_fail(d: Device, hall: DataHall) -> None:
    if not isinstance(d, CRACUnit):
        raise TypeError("CRAC_FAIL requires a CRACUnit device")
    d.state = DeviceState.FAILED
    d.fan_percent = 0.0
    # Hall ambient will rise on next physics tick — let the model handle it.
    _ = hall


def _switch_port_flap(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Switch):
        raise TypeError("SWITCH_PORT_FLAP requires a Switch device")
    d.state = DeviceState.DEGRADED
    d.port_up_count = max(0, d.port_up_count - 4)
    d.err_in_count += 10_000


def _disk_realloc_ramp(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Server):
        raise TypeError("DISK_REALLOC_RAMP requires a Server device")
    d.state = DeviceState.DEGRADED
    d.metadata["disk_reallocated_sectors"] = (
        int(d.metadata.get("disk_reallocated_sectors", 0)) + 500
    )


def _nic_packet_loss(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, Server):
        raise TypeError("NIC_PACKET_LOSS requires a Server device")
    d.state = DeviceState.DEGRADED
    d.metadata["nic_drop_rate"] = 0.05      # 5% packet drop


def _pdu_overload(d: Device, _hall: DataHall) -> None:
    if not isinstance(d, PDU):
        raise TypeError("PDU overload requires a PDU device")
    d.state = DeviceState.DEGRADED
    d.load_percent = 95.0


_HANDLERS: dict[FailureMode, Callable[[Device, DataHall], None]] = {
    FailureMode.GPU_ECC_RUNAWAY: _gpu_ecc_runaway,
    FailureMode.GPU_THERMAL_THROTTLE: _gpu_thermal_throttle,
    FailureMode.GPU_XID_43: _gpu_xid_43,
    FailureMode.PSU_EFFICIENCY_DRIFT: _psu_efficiency_drift,
    FailureMode.PSU_FAIL: _psu_fail,
    FailureMode.FAN_STUCK: _fan_stuck,
    FailureMode.CRAC_FAIL: _crac_fail,
    FailureMode.SWITCH_PORT_FLAP: _switch_port_flap,
    FailureMode.DISK_REALLOC_RAMP: _disk_realloc_ramp,
    FailureMode.NIC_PACKET_LOSS: _nic_packet_loss,
}


__all__ = ["inject", "clear"]

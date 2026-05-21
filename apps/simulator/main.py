"""Simulator entry point.

Purpose:
    Long-running loop that:
      1. Builds the site's `DataHall` objects from `sites.py` + `devices.py`.
      2. Each tick (default 1s wall-clock), evolves device utilization via
         `patterns.py`, then runs `physics.power` and `physics.thermal`.
      3. Emits a `TelemetryEvent` per (device, metric) to the Redis bus
         and persists to TimescaleDB asynchronously.

Ships: Week 2 (skeleton with deterministic metric emission); Week 3 wires
the physics engine through. Failure injection enters via the bus topic
`simulator.inject` (control plane and the inject script both write there).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
from datetime import datetime, timezone

from apps.agents.shared.event_bus import EventBus
from apps.agents.shared.logging import configure_logging, get_logger
from apps.ingestion.schema import CanonicalMetric, DeviceType, Severity, TelemetryEvent
from apps.physics.entities import CRACUnit, DataHall, GPU, PDU, Server, Switch
from apps.physics.power import compute_power_draw
from apps.physics.thermal import compute_thermal_state
from apps.simulator.devices import build_halls
from apps.simulator.patterns import apply_load_modulation
from apps.simulator.sites import get_site

log = get_logger(__name__)
TICK_SEC = 1.0


def _device_type_of(d: object) -> DeviceType:
    if isinstance(d, Server):
        return DeviceType.SERVER
    if isinstance(d, GPU):
        return DeviceType.GPU
    if isinstance(d, Switch):
        return DeviceType.SWITCH
    if isinstance(d, PDU):
        return DeviceType.PDU
    if isinstance(d, CRACUnit):
        return DeviceType.CRAC
    return DeviceType.SENSOR


def _emit_for_device(hall: DataHall, d: object) -> list[TelemetryEvent]:  # noqa: PLR0911
    """Build TelemetryEvents for every metric of this device on this tick."""
    common = {
        "site_id": hall.site_id,
        "hall_id": hall.id,
        "rack_id": getattr(d, "rack_id", "") or hall.id,
        "device_id": getattr(d, "id", "unknown"),
        "device_type": _device_type_of(d),
    }
    ts = datetime.now(timezone.utc)
    events: list[TelemetryEvent] = []

    def add(metric: CanonicalMetric, value: float | int | str, unit: str | None = None,
            severity: Severity = Severity.INFO) -> None:
        events.append(TelemetryEvent(
            timestamp=ts, metric=metric, value=value, unit=unit, severity=severity, **common,
        ))

    if isinstance(d, Server):
        add(CanonicalMetric.CPU_UTIL_PERCENT, round(d.cpu_util_percent, 2), "percent")
        add(CanonicalMetric.CPU_TEMP_CELSIUS, round(d.cpu_temp_c, 2), "celsius")
        add(CanonicalMetric.POWER_DRAW_WATTS, round(d.power_draw_w, 1), "watts")
        add(CanonicalMetric.PSU_EFFICIENCY_PERCENT, round(d.psu_efficiency_percent, 2), "percent")
        add(CanonicalMetric.FAN_RPM, d.fan_rpm, "rpm")
    elif isinstance(d, GPU):
        add(CanonicalMetric.GPU_UTIL_PERCENT, round(d.gpu_util_percent, 2), "percent")
        add(CanonicalMetric.GPU_TEMP_CELSIUS, round(d.gpu_temp_c, 2), "celsius")
        add(CanonicalMetric.GPU_POWER_WATTS, round(d.power_draw_w, 1), "watts")
        add(CanonicalMetric.GPU_ECC_CORRECTABLE, d.ecc_correctable_count, "count")
        add(CanonicalMetric.GPU_ECC_UNCORRECTABLE, d.ecc_uncorrectable_count, "count")
        if d.last_xid_code is not None:
            add(CanonicalMetric.GPU_XID_CODE, d.last_xid_code, "code", Severity.ERROR)
    elif isinstance(d, Switch):
        add(CanonicalMetric.NET_BPS_IN, d.bps_in, "bps")
        add(CanonicalMetric.NET_BPS_OUT, d.bps_out, "bps")
        add(CanonicalMetric.NET_ERR_IN, d.err_in_count, "count")
        add(CanonicalMetric.NET_PORT_UP, d.port_up_count, "count")
    elif isinstance(d, PDU):
        add(CanonicalMetric.PDU_LOAD_PERCENT, round(d.load_percent, 2), "percent")
    elif isinstance(d, CRACUnit):
        add(CanonicalMetric.CRAC_SUPPLY_CELSIUS, round(d.supply_temp_c, 2), "celsius")
        add(CanonicalMetric.CRAC_RETURN_CELSIUS, round(d.return_temp_c, 2), "celsius")
        add(CanonicalMetric.CRAC_FAN_PERCENT, round(d.fan_percent, 2), "percent")

    return events


async def tick(hall: DataHall, rng: random.Random, bus: EventBus) -> None:
    """Advance the hall by one tick and emit telemetry."""
    now = datetime.now(timezone.utc)
    for rack in hall.racks:
        for d in rack.devices:
            if isinstance(d, Server):
                d.cpu_util_percent = apply_load_modulation(d.cpu_util_percent, now, rng)
            elif isinstance(d, GPU):
                d.gpu_util_percent = apply_load_modulation(d.gpu_util_percent, now, rng)

    compute_power_draw(hall)
    compute_thermal_state(hall)

    events: list[TelemetryEvent] = []
    for rack in hall.racks:
        for d in rack.devices:
            events.extend(_emit_for_device(hall, d))
    for crac in hall.crac_units:
        events.extend(_emit_for_device(hall, crac))

    for ev in events:
        topic = f"telemetry.simulator.{ev.device_type.value}"
        await bus.publish(topic, ev)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=os.getenv("SITE_ID", "frankfurt"))
    parser.add_argument("--tick-sec", type=float, default=TICK_SEC)
    args = parser.parse_args()

    configure_logging()
    site = get_site(args.site)
    log.info("simulator.start", site_id=site.id, tick_sec=args.tick_sec)

    halls = build_halls(site)
    bus = EventBus.from_env()
    rng = random.Random(int(os.getenv("DEMO_RANDOM_SEED", "42")) + hash(site.id) % 10_000)

    try:
        while True:
            for hall in halls:
                await tick(hall, rng, bus)
            await asyncio.sleep(args.tick_sec)
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Power propagation model.

Purpose:
    Servers draw power as a function of CPU/GPU utilization. PSU efficiency
    curves modulate the wall draw. PDU load percent is the sum of its powered
    devices' wall draws divided by PDU capacity.

Ships: Week 3.
"""

from __future__ import annotations

from apps.physics.entities import CRACUnit, DataHall, GPU, PDU, Server


def compute_power_draw(hall: DataHall) -> None:
    """Update power_draw_w for every device in `hall`. In-place."""
    # Step 1: each device computes its own load-dependent draw.
    for rack in hall.racks:
        for d in rack.devices:
            if isinstance(d, Server):
                d.power_draw_w = _server_draw(d)
            elif isinstance(d, GPU):
                d.power_draw_w = _gpu_draw(d)
            elif isinstance(d, CRACUnit):
                d.power_draw_w = d.rated_power_w * (d.fan_percent / 100.0) ** 2

    # Step 2: PDU load = sum of its devices / capacity.
    pdus = [d for r in hall.racks for d in r.devices if isinstance(d, PDU)]
    powered_index: dict[str, list[float]] = {pdu.id: [] for pdu in pdus}
    for rack in hall.racks:
        for d in rack.devices:
            for pdu in pdus:
                if d.id in pdu.powered_device_ids:
                    powered_index[pdu.id].append(d.power_draw_w)
    for pdu in pdus:
        total = sum(powered_index[pdu.id])
        pdu.load_percent = min(100.0, (total / pdu.capacity_w) * 100.0 if pdu.capacity_w else 0.0)


def _server_draw(s: Server) -> float:
    """Server wall draw with a simple PSU efficiency model."""
    cpu_load_fraction = s.cpu_util_percent / 100.0
    dc_draw = 0.4 * s.rated_power_w + 0.6 * s.rated_power_w * cpu_load_fraction
    return dc_draw / max(0.50, s.psu_efficiency_percent / 100.0)


def _gpu_draw(g: GPU) -> float:
    """GPU draw scales near-linearly with utilization above a floor."""
    util_fraction = g.gpu_util_percent / 100.0
    return 0.15 * g.rated_power_w + 0.85 * g.rated_power_w * util_fraction


__all__ = ["compute_power_draw"]

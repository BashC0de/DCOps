"""Thermal model.

Purpose:
    Simple lumped thermal model for a data hall: each rack contributes heat
    proportional to its devices' power draw; CRAC units pull heat at their
    set capacity * fan_percent. Inlet/outlet temps per device are derived
    from the local heat load and air mixing factor.

Ships: Week 3 (full impl); Week 1 stub returns set-point ambient values.

Not a CFD model. Not accurate enough to publish a paper. Accurate enough
that Sentinel and Optimizer reason about plausible thermal failures.
"""

from __future__ import annotations

from apps.physics.entities import DataHall, Device, Rack


# Tunables — calibrated against Backblaze-style facility logs (Week 3).
_HEAT_RECIRCULATION_FACTOR = 0.15      # fraction of outlet air recirculating to inlet
_DEVICE_DELTA_T_PER_KW = 8.0           # rough °C rise per kW dissipated
_AMBIENT_CEILING_C = 45.0              # cap on inlet temp if cooling fails


def compute_thermal_state(hall: DataHall) -> None:
    """Update inlet/outlet temps for every device in `hall`.

    Mutates devices in place. Called once per simulator tick.

    TODO(week-3): full lumped model. For now we apply a coarse heuristic
    so the simulator can produce *some* plausible variance.
    """
    total_heat_kw = sum(d.power_draw_w for r in hall.racks for d in r.devices) / 1000.0
    cooling_capacity_kw = sum(c.capacity_kw * (c.fan_percent / 100.0) for c in hall.crac_units)
    cooling_deficit_kw = max(0.0, total_heat_kw - cooling_capacity_kw)

    # If we're behind on cooling, inlet temp rises proportionally.
    extra_c = min(_AMBIENT_CEILING_C - hall.ambient_inlet_c, cooling_deficit_kw * 0.4)
    base_inlet = hall.ambient_inlet_c + extra_c

    for rack in hall.racks:
        _update_rack(rack, base_inlet_c=base_inlet)


def _update_rack(rack: Rack, base_inlet_c: float) -> None:
    rack_kw = sum(d.power_draw_w for d in rack.devices) / 1000.0
    rack_delta_t = rack_kw * _DEVICE_DELTA_T_PER_KW / max(1, len(rack.devices))

    for d in rack.devices:
        d.inlet_temp_c = base_inlet_c + _HEAT_RECIRCULATION_FACTOR * rack_delta_t
        d.outlet_temp_c = d.inlet_temp_c + _delta_t_for_device(d)


def _delta_t_for_device(d: Device) -> float:
    """Per-device temperature rise across its airpath."""
    # crude scaling: device delta-T proportional to its share of rated power
    return 4.0 + (d.power_draw_w / 1000.0) * _DEVICE_DELTA_T_PER_KW * 0.25


__all__ = ["compute_thermal_state"]

"""Build out a site's devices from its `SiteSpec`.

Produces a fully-populated `DataHall` with racks, servers, GPUs (where
density allows), switches, PDUs, and one CRAC per hall. Deterministic
given `DEMO_RANDOM_SEED`.

Ships: Week 2.
"""

from __future__ import annotations

import os
import random

from apps.physics.entities import CRACUnit, DataHall, GPU, PDU, Rack, Server, Switch
from apps.simulator.sites import SiteSpec


def _seeded_rng() -> random.Random:
    return random.Random(int(os.getenv("DEMO_RANDOM_SEED", "42")))


def build_halls(site: SiteSpec) -> list[DataHall]:
    """Instantiate every device in a site, returning a list of `DataHall`s."""
    rng = _seeded_rng()
    halls: list[DataHall] = []

    for h_idx in range(site.halls):
        hall_id = f"{site.id}-h{h_idx + 1}"
        crac = CRACUnit(
            id=f"{hall_id}-crac1",
            type="crac",
            model="Vertiv-Liebert-DSE-080",
            vendor="Vertiv",
            rack_id="",                     # CRACs aren't in a rack
            hall_id_serves=hall_id,
            capacity_kw=80.0,
            rated_power_w=8_000.0,
            supply_temp_c=site.ambient_inlet_c - 4,
            return_temp_c=site.ambient_inlet_c + 8,
            fan_percent=55.0,
        )

        hall = DataHall(
            id=hall_id,
            site_id=site.id,
            capacity_kw=400.0,
            crac_units=[crac],
            ambient_inlet_c=site.ambient_inlet_c,
        )

        for r_idx in range(site.racks_per_hall):
            rack_id = f"{hall_id}-r{r_idx + 1:02d}"
            rack = Rack(id=rack_id, hall_id=hall_id, position=(r_idx // 5, r_idx % 5))

            # Each rack: 1 ToR switch, 2 PDUs (A+B), ~10 servers, GPUs by density.
            tor = Switch(
                id=f"{rack_id}-tor",
                type="switch",
                model="Arista-7050X3",
                vendor="Arista",
                rack_id=rack_id,
                port_count=48,
                port_up_count=44,
                rated_power_w=250.0,
            )
            rack.devices.append(tor)

            pdu_a = PDU(
                id=f"{rack_id}-pdu-a",
                type="pdu",
                model="APC-AP8959",
                vendor="APC",
                rack_id=rack_id,
                capacity_w=15_000.0,
                rated_power_w=20.0,
            )
            pdu_b = PDU(
                id=f"{rack_id}-pdu-b",
                type="pdu",
                model="APC-AP8959",
                vendor="APC",
                rack_id=rack_id,
                capacity_w=15_000.0,
                rated_power_w=20.0,
            )
            rack.devices.extend([pdu_a, pdu_b])

            for s_idx in range(10):
                srv_id = f"{rack_id}-srv{s_idx + 1:02d}"
                srv = Server(
                    id=srv_id,
                    type="server",
                    model=rng.choice(["Dell-R760xa", "HPE-DL380-Gen11", "Supermicro-SYS-821GE"]),
                    vendor=rng.choice(["Dell", "HPE", "Supermicro"]),
                    rack_id=rack_id,
                    cpu_util_percent=rng.uniform(20.0, 60.0),
                    rated_power_w=rng.choice([600.0, 800.0, 1000.0]),
                    psu_efficiency_percent=rng.uniform(92.0, 96.0),
                )
                rack.devices.append(srv)
                pdu_a.powered_device_ids.append(srv_id)

                # GPU allocation by site density.
                if rng.random() < site.gpu_density_percent:
                    for g_idx in range(rng.choice([1, 2, 4, 8])):
                        gpu_id = f"{srv_id}-gpu{g_idx + 1}"
                        gpu = GPU(
                            id=gpu_id,
                            type="gpu",
                            model=rng.choice(["NVIDIA-H100-80GB", "NVIDIA-A100-80GB"]),
                            vendor="NVIDIA",
                            rack_id=rack_id,
                            parent_server_id=srv_id,
                            gpu_util_percent=rng.uniform(40.0, 90.0),
                            rated_power_w=700.0,
                        )
                        rack.devices.append(gpu)

            hall.racks.append(rack)

        halls.append(hall)

    return halls


__all__ = ["build_halls"]

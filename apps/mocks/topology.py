"""Deterministic device topology used by the mock vendor endpoints.

Generates a small, fixed inventory per site so the normalizers always see
the same device IDs across restarts. Independent of the physics
simulator's richer topology — these mocks exist to validate the data path
shape, not the physics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class MockDevice:
    id: str
    type: Literal["server", "gpu", "switch", "pdu", "crac", "sensor"]
    rack_id: str
    hall_id: str
    site_id: str
    model: str
    vendor: str
    parent_id: str | None = None    # for GPUs nested in a server


@dataclass(frozen=True)
class MockTopology:
    site_id: str
    devices: tuple[MockDevice, ...] = field(default_factory=tuple)

    def by_id(self, device_id: str) -> MockDevice | None:
        for d in self.devices:
            if d.id == device_id:
                return d
        return None

    def by_type(self, type_: str) -> list[MockDevice]:
        return [d for d in self.devices if d.type == type_]


def build_topology(
    site_id: str,
    *,
    halls: int = 2,
    racks_per_hall: int = 3,
    servers_per_rack: int = 4,
    gpu_density: float = 0.5,
) -> MockTopology:
    """Build a small deterministic inventory for `site_id`.

    Smaller than the full simulator topology — the mock service is for
    shape validation, not load testing. Defaults give ~50 devices/site.
    """
    devices: list[MockDevice] = []
    for h in range(halls):
        hall_id = f"{site_id}-h{h + 1}"
        devices.append(
            MockDevice(
                id=f"{hall_id}-crac1",
                type="crac",
                rack_id="",
                hall_id=hall_id,
                site_id=site_id,
                model="Vertiv-Liebert-DSE-080",
                vendor="Vertiv",
            )
        )
        for r in range(racks_per_hall):
            rack_id = f"{hall_id}-r{r + 1:02d}"
            devices.append(
                MockDevice(
                    id=f"{rack_id}-tor",
                    type="switch",
                    rack_id=rack_id,
                    hall_id=hall_id,
                    site_id=site_id,
                    model="Arista-7050X3",
                    vendor="Arista",
                )
            )
            for pdu_letter in ("a", "b"):
                devices.append(
                    MockDevice(
                        id=f"{rack_id}-pdu-{pdu_letter}",
                        type="pdu",
                        rack_id=rack_id,
                        hall_id=hall_id,
                        site_id=site_id,
                        model="APC-AP8959",
                        vendor="APC",
                    )
                )
            for s in range(servers_per_rack):
                srv_id = f"{rack_id}-srv{s + 1:02d}"
                devices.append(
                    MockDevice(
                        id=srv_id,
                        type="server",
                        rack_id=rack_id,
                        hall_id=hall_id,
                        site_id=site_id,
                        model="Dell-R760xa",
                        vendor="Dell",
                    )
                )
                # Deterministic GPU presence — hash of srv_id picks below cutoff.
                if (hash(srv_id) & 0xFFFF) / 0xFFFF < gpu_density:
                    for g in range(2):
                        devices.append(
                            MockDevice(
                                id=f"{srv_id}-gpu{g + 1}",
                                type="gpu",
                                rack_id=rack_id,
                                hall_id=hall_id,
                                site_id=site_id,
                                model="NVIDIA-H100-80GB",
                                vendor="NVIDIA",
                                parent_id=srv_id,
                            )
                        )
    return MockTopology(site_id=site_id, devices=tuple(devices))


__all__ = ["MockDevice", "MockTopology", "build_topology"]

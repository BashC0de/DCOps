"""Site topology definitions.

Three simulated sites with distinct climates + size profiles so cross-site
correlations are interesting:

    Frankfurt — cooler ambient, mature, mid-size (60 racks across 3 halls)
    Singapore — hot/humid, GPU-heavy (60 racks across 3 halls)
    Mumbai    — variable ambient, mixed workload (60 racks across 3 halls)

Each site has 20 racks total in the spec (3 sites × 20 racks), but we split
across 3 halls per site for richer thermal isolation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    id: str
    region: str
    timezone: str
    ambient_inlet_c: float
    halls: int
    racks_per_hall: int
    gpu_density_percent: float            # what fraction of servers carry GPUs


SITES: list[SiteSpec] = [
    SiteSpec(
        id="frankfurt",
        region="eu-central-1",
        timezone="Europe/Berlin",
        ambient_inlet_c=20.0,
        halls=2,
        racks_per_hall=10,
        gpu_density_percent=0.35,
    ),
    SiteSpec(
        id="singapore",
        region="ap-southeast-1",
        timezone="Asia/Singapore",
        ambient_inlet_c=24.0,
        halls=2,
        racks_per_hall=10,
        gpu_density_percent=0.65,
    ),
    SiteSpec(
        id="mumbai",
        region="ap-south-1",
        timezone="Asia/Kolkata",
        ambient_inlet_c=23.0,
        halls=2,
        racks_per_hall=10,
        gpu_density_percent=0.45,
    ),
]


def get_site(site_id: str) -> SiteSpec:
    for s in SITES:
        if s.id == site_id:
            return s
    raise LookupError(f"Unknown site: {site_id}")


__all__ = ["SITES", "SiteSpec", "get_site"]

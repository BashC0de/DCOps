"""Workload placement model.

Purpose:
    Represents synthetic workloads (training jobs, inference services, web
    tiers) and their placement on devices. Optimizer reads this to choose
    migration recommendations; failure_injector can move workloads around
    as part of a rollback scenario.

Ships: Week 3 (data classes); placement logic Week 7 alongside Optimizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WorkloadTier(StrEnum):
    """Reliability/priority tier. Optimizer respects anti-affinity within a tier."""

    PRODUCTION_CRITICAL = "production_critical"
    PRODUCTION_STANDARD = "production_standard"
    BATCH = "batch"
    DEV = "dev"


@dataclass
class Workload:
    """A logical unit of work mapped onto one or more devices."""

    id: str
    name: str
    tier: WorkloadTier
    owner: str
    placed_on_device_ids: list[str] = field(default_factory=list)
    requested_cpu_cores: float = 4.0
    requested_mem_bytes: int = 16 * 1024**3
    requested_gpu_count: int = 0
    requested_power_w: float = 200.0      # rough estimate for placement
    anti_affinity_group: str | None = None


__all__ = ["Workload", "WorkloadTier"]

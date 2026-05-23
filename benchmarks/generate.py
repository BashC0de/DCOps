"""Deterministic 200-scenario generator.

Produces `Scenario` objects in memory rather than writing 200 YAML files —
avoids churn in the repo and keeps generation reproducible from a seed.
The five hand-written YAMLs under `benchmarks/scenarios/*.yml` stay as the
"golden" curated set; this module fills the rest by enumerating
(category × failure_mode × site × device_pick × variant).

Coverage matrix (default `target=200`, seed=42):
    gpu        × 5 failure modes × 3 sites × 4 picks  = 60
    psu        × 2 failure modes × 3 sites × 4 picks  = 24
    thermal    × 2 failure modes × 3 sites × 4 picks  = 24
    cooling    × 1 failure mode  × 3 sites × 4 picks  = 12
    network    × 1 failure mode  × 3 sites × 4 picks  = 12
    storage    × 1 failure mode  × 3 sites × 4 picks  = 12
    multi      × 4 cascading shapes × 3 sites          = 12
    federated  × 4 cross-site shapes                    =  4
    ─────────────────────────────────────────────────────────
                                                       = 160 generated
                                                       +  5 hand-written
                                                       + 35 randomized variants
                                                       = 200

The randomized variants pad up to the target by re-rolling device picks
inside the same category space. Deterministic given the seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from apps.physics.entities import FailureMode
from apps.simulator.scenarios import Scenario, ScenarioStep, list_available, load

SITES: tuple[str, ...] = ("frankfurt", "singapore", "mumbai")


@dataclass(frozen=True)
class _Variant:
    category: str
    failure_mode: FailureMode
    device_type: str
    expected_detection_kind: str
    expected_root_cause: str
    expected_actions: tuple[str, ...]


_VARIANTS: tuple[_Variant, ...] = (
    # GPU
    _Variant("gpu", FailureMode.GPU_ECC_RUNAWAY, "gpu", "gpu_ecc_runaway",
             "GPU memory cell wear-out; correctable ECC count crossed threshold.",
             ("workload_migration",)),
    _Variant("gpu", FailureMode.GPU_THERMAL_THROTTLE, "gpu", "gpu_thermal",
             "GPU thermal throttling; rack inlet or fan capacity exceeded.",
             ("workload_migration", "fan_speed_adjust")),
    _Variant("gpu", FailureMode.GPU_XID_43, "gpu", "gpu_fatal_xid",
             "NVIDIA XID 43 — GPU stopped responding to commands.",
             ("workload_migration",)),
    _Variant("gpu", FailureMode.GPU_THERMAL_THROTTLE, "gpu", "gpu_thermal",
             "GPU thermal throttle following hall ambient rise.",
             ("workload_migration", "fan_speed_adjust")),
    _Variant("gpu", FailureMode.GPU_ECC_RUNAWAY, "gpu", "gpu_ecc_runaway",
             "Progressive ECC drift suggests pending uncorrectable event.",
             ("workload_migration",)),

    # PSU
    _Variant("psu", FailureMode.PSU_EFFICIENCY_DRIFT, "server", "psu_efficiency_drift",
             "PSU efficiency dropped below 85% — capacitor aging.",
             ("workload_migration",)),
    _Variant("psu", FailureMode.PSU_FAIL, "server", "psu_failure",
             "PSU complete failure; rack draw should be picked up by the redundant unit.",
             ("workload_migration",)),

    # Thermal
    _Variant("thermal", FailureMode.FAN_STUCK, "server", "thermal_cascade",
             "Fan stuck at 0 RPM while CPU temp rises into throttle range.",
             ("fan_speed_adjust", "workload_migration")),
    _Variant("thermal", FailureMode.GPU_THERMAL_THROTTLE, "gpu", "gpu_thermal",
             "Thermal envelope exceeded; mixed CPU+GPU contributors.",
             ("workload_migration",)),

    # Cooling
    _Variant("cooling", FailureMode.CRAC_FAIL, "crac", "crac_failure",
             "CRAC unit failed; hall ambient will rise without compensation.",
             ("workload_migration",)),

    # Network
    _Variant("network", FailureMode.SWITCH_PORT_FLAP, "switch", "switch_port_flap",
             "ToR switch ports flapping; intermittent connectivity for rack.",
             ()),  # no automated remediation by default

    # Storage
    _Variant("storage", FailureMode.DISK_REALLOC_RAMP, "server", "disk_smart_drift",
             "Disk reallocated sector count rising; SMART says pre-failure.",
             ()),
)


def _site_picks() -> tuple[str, ...]:
    return SITES


def _device_selectors(category: str, device_type: str, n: int) -> list[dict[str, str]]:
    """Build `n` deterministic device selectors for `device_type`."""
    return [
        {"type": device_type, "rack": "any", "pick_strategy": f"hash_{i}"}
        for i in range(n)
    ]


def _scenario_from_variant(
    variant: _Variant, site: str, pick: dict[str, str], suffix: str
) -> Scenario:
    name = f"gen_{variant.category}_{variant.failure_mode.value}_{site}_{suffix}"
    step = ScenarioStep(
        delay_seconds=0.0,
        device_selector=pick,
        failure_mode=variant.failure_mode,
    )
    return Scenario(
        name=name,
        description=(
            f"Auto-generated {variant.category} scenario — "
            f"{variant.failure_mode.value} at {site}."
        ),
        steps=[step],
        expected_detection={
            "agent": "sentinel",
            "within_seconds": 90,
            "failure_kind": variant.expected_detection_kind,
            "min_probability": 0.6,
        },
        expected_root_cause=variant.expected_root_cause,
        expected_actions=list(variant.expected_actions),
    )


def _multi_signal_scenarios() -> list[Scenario]:
    """Hand-crafted cascading scenarios for the `multi` category."""
    out: list[Scenario] = []
    for site in SITES:
        out.append(
            Scenario(
                name=f"gen_multi_fan_psu_{site}",
                description="Fan stuck → CPU throttles → PSU efficiency drifts.",
                steps=[
                    ScenarioStep(
                        delay_seconds=0.0,
                        device_selector={"type": "server", "rack": "any"},
                        failure_mode=FailureMode.FAN_STUCK,
                    ),
                    ScenarioStep(
                        delay_seconds=30.0,
                        device_selector={"type": "server", "rack": "same"},
                        failure_mode=FailureMode.PSU_EFFICIENCY_DRIFT,
                    ),
                ],
                expected_detection={
                    "agent": "sentinel",
                    "within_seconds": 120,
                    "failure_kind": "thermal_cascade",
                    "min_probability": 0.6,
                },
                expected_root_cause=(
                    "Fan failure caused thermal stress; PSU efficiency drifted "
                    "under sustained load."
                ),
                expected_actions=["workload_migration", "fan_speed_adjust"],
            )
        )
        out.append(
            Scenario(
                name=f"gen_multi_crac_cascade_{site}",
                description="CRAC fail → multi-rack inlet rise.",
                steps=[
                    ScenarioStep(
                        delay_seconds=0.0,
                        device_selector={"type": "crac", "hall": "any"},
                        failure_mode=FailureMode.CRAC_FAIL,
                    ),
                ],
                expected_detection={
                    "agent": "sentinel",
                    "within_seconds": 180,
                    "failure_kind": "gpu_thermal",
                    "min_probability": 0.6,
                },
                expected_root_cause=(
                    "CRAC unit failure; hall ambient rose, GPUs throttle."
                ),
                expected_actions=["workload_migration"],
            )
        )
    return out


def _federated_scenarios() -> list[Scenario]:
    """Cross-site scenarios — the correlator should propagate the rule."""
    pairs = [
        ("frankfurt", "singapore"),
        ("frankfurt", "mumbai"),
        ("singapore", "mumbai"),
        ("mumbai", "frankfurt"),
    ]
    out: list[Scenario] = []
    for origin, _target in pairs:
        out.append(
            Scenario(
                name=f"gen_federated_gpu_ecc_{origin}",
                description=(
                    f"Repeated GPU ECC at {origin}; correlator should broadcast a "
                    "shadow-mode candidate to the other sites."
                ),
                steps=[
                    ScenarioStep(
                        delay_seconds=0.0,
                        device_selector={"type": "gpu", "rack": "any"},
                        failure_mode=FailureMode.GPU_ECC_RUNAWAY,
                    ),
                ],
                expected_detection={
                    "agent": "sentinel",
                    "within_seconds": 90,
                    "failure_kind": "gpu_ecc_runaway",
                    "min_probability": 0.7,
                    "expect_propagation": True,
                },
                expected_root_cause="GPU memory wear; cross-site candidate broadcast.",
                expected_actions=["workload_migration"],
            )
        )
    return out


def generate(target: int = 200, seed: int = 42) -> list[Scenario]:
    """Produce a deterministic list of `target` scenarios."""
    rng = random.Random(seed)
    out: list[Scenario] = []

    # 1. Hand-written curated scenarios.
    for name in list_available():
        out.append(load(name))

    # 2. Cross-product of variants × sites × picks.
    for v in _VARIANTS:
        picks = _device_selectors(v.category, v.device_type, n=4)
        for site in SITES:
            for i, pick in enumerate(picks):
                out.append(_scenario_from_variant(v, site, pick, suffix=str(i)))
                if len(out) >= target:
                    return out

    # 3. Multi-signal cascading + federated.
    out.extend(_multi_signal_scenarios())
    out.extend(_federated_scenarios())

    # 4. Pad with randomised re-rolls of (variant × site × pick).
    while len(out) < target:
        v = rng.choice(_VARIANTS)
        site = rng.choice(SITES)
        pick = {
            "type": v.device_type,
            "rack": "any",
            "pick_strategy": f"random_{rng.randint(0, 9999)}",
        }
        suffix = f"r{len(out):03d}"
        out.append(_scenario_from_variant(v, site, pick, suffix=suffix))

    return out[:target]


def categorise(name: str) -> str:
    """Bucket a scenario name into a coarse category for report aggregation."""
    if name.startswith("gen_"):
        # gen_<category>_<...>
        return name.split("_", 2)[1]
    # Curated names: derive from contents.
    for token, cat in (
        ("gpu", "gpu"),
        ("psu", "psu"),
        ("thermal", "thermal"),
        ("crac", "cooling"),
        ("switch", "network"),
        ("disk", "storage"),
    ):
        if token in name.lower():
            return cat
    return "other"


def categorise_many(scenarios: Iterable[Scenario]) -> dict[str, list[Scenario]]:
    out: dict[str, list[Scenario]] = {}
    for s in scenarios:
        out.setdefault(categorise(s.name), []).append(s)
    return out


__all__ = ["SITES", "generate", "categorise", "categorise_many"]

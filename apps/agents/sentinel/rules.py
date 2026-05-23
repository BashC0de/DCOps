"""Rule-based detection for deterministic failure signals.

These signals don't need a model — they're either explicit hardware
codes (NVIDIA XID) or unambiguous threshold breaches (uncorrectable
ECC > 0, fan stuck at 0 RPM with rising CPU temp). Each rule fires
independently and produces a `RuleHit` with a calibrated probability.

The set of rules below is intentionally narrow and high-precision —
false positives erode trust faster than false negatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.agents.sentinel.window import DeviceWindow
from apps.ingestion.schema import CanonicalMetric


@dataclass(frozen=True)
class RuleHit:
    """A rule's positive determination for one device."""

    rule_id: str
    failure_kind: str
    probability: float           # 0..1 — calibrated to historical TPR
    horizon_hours: float         # how soon failure is expected
    evidence: dict[str, Any]     # which observations triggered this rule


# NVIDIA XID codes that historically correlate with hardware failure.
# Curated from NVIDIA's Xid Errors documentation:
#   - 43, 44, 45  → memory-page retirement / DBE
#   - 48          → DBE on memory
#   - 63, 64      → ECC page retirement
#   - 79          → GPU fallen off the bus
#   - 92          → high single-bit ECC errors
_FATAL_XID_CODES: frozenset[int] = frozenset({43, 44, 45, 48, 63, 64, 79, 92})


def _last_value(window: DeviceWindow, metric: CanonicalMetric) -> float | None:
    rows = window.recent_for_metric(metric.value)
    if not rows:
        return None
    v = rows[-1].get("value")
    return float(v) if isinstance(v, (int, float)) else None


def _max_value(window: DeviceWindow, metric: CanonicalMetric) -> float | None:
    rows = window.recent_for_metric(metric.value)
    if not rows:
        return None
    nums = [float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float))]
    return max(nums) if nums else None


def _sum_value(window: DeviceWindow, metric: CanonicalMetric) -> float:
    rows = window.recent_for_metric(metric.value)
    return sum(float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float)))


# --- Individual rules -----------------------------------------------------------

def _rule_fatal_xid(window: DeviceWindow) -> RuleHit | None:
    """Any fatal XID code in the window → almost certain GPU failure."""
    xid = _last_value(window, CanonicalMetric.GPU_XID_CODE)
    if xid is None:
        return None
    code = int(xid)
    if code in _FATAL_XID_CODES:
        return RuleHit(
            rule_id="gpu_fatal_xid",
            failure_kind="gpu_fatal_xid",
            probability=0.98,
            horizon_hours=1.0,
            evidence={"xid_code": code},
        )
    return None


def _rule_uncorrectable_ecc(window: DeviceWindow) -> RuleHit | None:
    """Any uncorrectable ECC error is a hard signal for GPU memory failure."""
    uncorr = _max_value(window, CanonicalMetric.GPU_ECC_UNCORRECTABLE)
    if uncorr is None or uncorr <= 0:
        return None
    return RuleHit(
        rule_id="gpu_uncorrectable_ecc",
        failure_kind="gpu_ecc_runaway",
        probability=0.9,
        horizon_hours=6.0,
        evidence={"max_uncorrectable_ecc": uncorr},
    )


def _rule_correctable_ecc_storm(window: DeviceWindow) -> RuleHit | None:
    """A spike in correctable ECC often precedes uncorrectable failures."""
    total = _sum_value(window, CanonicalMetric.GPU_ECC_CORRECTABLE)
    if total < 10_000:
        return None
    return RuleHit(
        rule_id="gpu_correctable_ecc_storm",
        failure_kind="gpu_ecc_drift",
        probability=0.75,
        horizon_hours=24.0,
        evidence={"correctable_ecc_window_total": total},
    )


def _rule_gpu_thermal_runaway(window: DeviceWindow) -> RuleHit | None:
    """GPU temp > 90 °C is the throttle floor; sustained spikes risk damage."""
    peak = _max_value(window, CanonicalMetric.GPU_TEMP_CELSIUS)
    if peak is None or peak < 90.0:
        return None
    return RuleHit(
        rule_id="gpu_thermal_runaway",
        failure_kind="gpu_thermal",
        probability=0.7,
        horizon_hours=2.0,
        evidence={"max_gpu_temp_c": peak},
    )


def _rule_fan_stuck_hot_cpu(window: DeviceWindow) -> RuleHit | None:
    """0-RPM fan WITH a CPU temp above 80 °C → forced thermal failure path."""
    fan = _last_value(window, CanonicalMetric.FAN_RPM)
    cpu = _max_value(window, CanonicalMetric.CPU_TEMP_CELSIUS)
    if fan is None or cpu is None:
        return None
    if fan <= 1.0 and cpu >= 80.0:
        return RuleHit(
            rule_id="fan_stuck_hot_cpu",
            failure_kind="thermal_cascade",
            probability=0.85,
            horizon_hours=1.0,
            evidence={"fan_rpm": fan, "max_cpu_temp_c": cpu},
        )
    return None


def _rule_disk_reallocated_burst(window: DeviceWindow) -> RuleHit | None:
    """Backblaze: reallocated sector count rising > 50 in window → drive risk."""
    rows = window.recent_for_metric(CanonicalMetric.DISK_REALLOCATED_SECTORS.value)
    if len(rows) < 2:
        return None
    nums = [float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float))]
    if len(nums) < 2:
        return None
    delta = nums[-1] - nums[0]
    if delta < 50.0:
        return None
    return RuleHit(
        rule_id="disk_reallocated_burst",
        failure_kind="disk_smart_drift",
        probability=0.65,
        horizon_hours=48.0,
        evidence={"reallocated_delta": delta, "current": nums[-1]},
    )


def _rule_psu_efficiency_drop(window: DeviceWindow) -> RuleHit | None:
    """PSU efficiency falling below 85% (from healthy 93-95) signals drift."""
    rows = window.recent_for_metric(CanonicalMetric.PSU_EFFICIENCY_PERCENT.value)
    if len(rows) < 5:
        return None
    nums = [float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float))]
    if not nums:
        return None
    recent_avg = sum(nums[-5:]) / min(5, len(nums))
    if recent_avg >= 85.0:
        return None
    return RuleHit(
        rule_id="psu_efficiency_drop",
        failure_kind="psu_efficiency_drift",
        probability=0.6,
        horizon_hours=72.0,
        evidence={"recent_avg_efficiency_pct": recent_avg},
    )


_ALL_RULES = (
    _rule_fatal_xid,
    _rule_uncorrectable_ecc,
    _rule_correctable_ecc_storm,
    _rule_gpu_thermal_runaway,
    _rule_fan_stuck_hot_cpu,
    _rule_disk_reallocated_burst,
    _rule_psu_efficiency_drop,
)


def evaluate(window: DeviceWindow) -> list[RuleHit]:
    """Run every rule against `window` and return all firing rules."""
    hits: list[RuleHit] = []
    for rule in _ALL_RULES:
        hit = rule(window)
        if hit is not None:
            hits.append(hit)
    return hits


__all__ = ["RuleHit", "evaluate"]

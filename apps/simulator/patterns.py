"""Synthetic workload patterns.

Diurnal + seasonal + noise modulation applied to device utilization so the
generated telemetry doesn't look like a stuck dial. Used by the simulator's
tick loop.

Ships: Week 2.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone


def diurnal_load(now: datetime, base: float = 0.5, amplitude: float = 0.25) -> float:
    """Return a 0..1 multiplier modeling daily load: peak ~14:00 local, trough ~04:00.

    `now` should be a timezone-aware datetime for the site's local time.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = now.hour + now.minute / 60.0
    # Sinusoidal with peak at 14:00 (phase shift).
    return max(0.0, min(1.0, base + amplitude * math.sin((hours - 8.0) / 24.0 * 2 * math.pi)))


def weekly_modulation(now: datetime, weekday_amp: float = 0.1) -> float:
    """Slight dip on weekends."""
    return -weekday_amp if now.weekday() >= 5 else 0.0


def jitter(rng: random.Random, std: float = 0.05) -> float:
    """Gaussian noise centered at 0."""
    return rng.gauss(0.0, std)


def apply_load_modulation(
    base_value: float,
    now: datetime,
    rng: random.Random,
    swing_fraction: float = 0.4,
) -> float:
    """Combine diurnal + weekly + jitter into a single multiplier."""
    multiplier = (
        diurnal_load(now)
        + weekly_modulation(now)
        + jitter(rng, std=0.04)
    )
    swing = base_value * swing_fraction
    return max(0.0, base_value + swing * (multiplier - 0.5) * 2)


__all__ = ["diurnal_load", "weekly_modulation", "jitter", "apply_load_modulation"]

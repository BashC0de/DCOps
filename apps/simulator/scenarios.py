"""Pre-built failure scenario loader.

Reads YAML from benchmarks/scenarios/ and applies them via the physics
engine's failure injector. Bridges scripted demo scenes to the runtime.

Ships: Week 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from apps.physics.entities import FailureMode

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


@dataclass
class ScenarioStep:
    """One injection step within a multi-stage scenario."""

    delay_seconds: float
    device_selector: dict[str, str]       # e.g. {"type": "gpu", "rack": "fra-h1-r07"}
    failure_mode: FailureMode
    duration_seconds: float | None = None  # None = persistent until cleared


@dataclass
class Scenario:
    """A full named scenario (one or more injection steps)."""

    name: str
    description: str
    steps: list[ScenarioStep]
    expected_detection: dict[str, Any]
    expected_root_cause: str
    expected_actions: list[str]


def load(name: str) -> Scenario:
    """Load a scenario YAML by filename (without .yml)."""
    path = SCENARIO_DIR / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    with path.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    steps = [
        ScenarioStep(
            delay_seconds=float(s.get("delay_seconds", 0.0)),
            device_selector=dict(s["device_selector"]),
            failure_mode=FailureMode(s["failure_mode"]),
            duration_seconds=s.get("duration_seconds"),
        )
        for s in raw["steps"]
    ]
    return Scenario(
        name=raw["name"],
        description=raw.get("description", ""),
        steps=steps,
        expected_detection=raw.get("expected_detection", {}),
        expected_root_cause=raw.get("expected_root_cause", ""),
        expected_actions=raw.get("expected_actions", []),
    )


def list_available() -> list[str]:
    """Return the basenames of all scenario YAMLs."""
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.yml"))


__all__ = ["Scenario", "ScenarioStep", "load", "list_available"]

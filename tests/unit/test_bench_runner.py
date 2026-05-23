"""Tests for the benchmark runner outcome collection.

We script a fake bus that returns canned `predictions.failure`,
`incidents.report`, and `recommendations.*` events when the runner
publishes `simulator.inject` — so the full scoring path runs without
docker or the real simulator.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from benchmarks.runner import ScenarioResult, _rca_match, run_one
from benchmarks.generate import generate

pytestmark = pytest.mark.unit


# --- fake bus -----------------------------------------------------------------


@dataclass
class _ScriptedBus:
    """Each publish to `simulator.inject` triggers scripted downstream events."""

    publishes: list[tuple[str, Any]] = field(default_factory=list)
    _subs: dict[str, list[asyncio.Queue]] = field(default_factory=dict)
    scripted: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _client: Any = None
    delay_s: float = 0.01

    async def publish(self, topic: str, event: Any) -> int:
        payload = _to_dict(event)
        self.publishes.append((topic, payload))
        for pat, queues in self._subs.items():
            if _pattern_matches(pat, topic):
                for q in queues:
                    await q.put(payload)

        if topic == "simulator.inject":
            # Fan out scripted downstream events after a tiny delay.
            await asyncio.sleep(self.delay_s)
            for follow_topic, events in self.scripted.items():
                for ev in events:
                    for pat, queues in self._subs.items():
                        if _pattern_matches(pat, follow_topic):
                            for q in queues:
                                await q.put(ev)
        return 1

    async def subscribe(self, pattern: str):  # noqa: ANN201
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(pattern, []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            try:
                self._subs[pattern].remove(q)
            except ValueError:
                pass

    async def close(self) -> None:
        pass


def _to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")  # type: ignore[no-any-return]
    if hasattr(event, "model_dump_json"):
        return json.loads(event.model_dump_json())
    return dict(event)


def _pattern_matches(pattern: str, topic: str) -> bool:
    if pattern.endswith("*"):
        return topic.startswith(pattern[:-1])
    return pattern == topic


def _gpu_ecc_scenario():
    scenarios = generate(target=200)
    return next(s for s in scenarios if s.name == "gpu_ecc_failure")


# --- tests --------------------------------------------------------------------


def test_rca_match_substring_keywords() -> None:
    # ≥ 2 substring hits over tokens longer than 4 chars.
    assert _rca_match(
        "GPU memory failure with rising correctable counts.",
        "GPU memory failure: correctable ECC counts climbing.",
    )
    assert not _rca_match(
        "CRAC unit failure with thermal cascade",
        "PSU degradation observed in another rack",
    )


async def test_run_one_records_detection_and_rca() -> None:
    scenario = _gpu_ecc_scenario()
    bus = _ScriptedBus(
        scripted={
            "predictions.failure": [
                {
                    "site_id": "frankfurt",
                    "device_id": "frankfurt-h1-r07-srv03-gpu1",
                    "failure_kind": "gpu_ecc_runaway",
                    "probability": 0.9,
                    "timestamp": "2026-05-23T00:00:00+00:00",
                },
            ],
            "incidents.report": [
                {
                    "site_id": "frankfurt",
                    "incident_id": str(uuid4()),
                    "metadata": {
                        "summary": "GPU memory cell wear-out with rising correctable ECC counts.",
                    },
                    "llm_cost_usd": 0.0042,
                },
            ],
            "recommendations.workload_migration": [
                {
                    "site_id": "frankfurt",
                    "kind": "workload_migration",
                    "target_device_ids": ["frankfurt-h1-r07-srv03"],
                    "confidence": 0.85,
                    "parameters": {"moves": []},
                    "estimated_impact": {},
                    "requires_human_approval": False,
                },
            ],
        }
    )
    result = await run_one(scenario, bus, detection_timeout_s=2.0, grace_s=0.5)
    assert isinstance(result, ScenarioResult)
    assert result.detected is True
    assert result.detection_latency_sec is not None
    assert result.detection_latency_sec >= 0
    assert result.rca_top1_match is True
    assert "workload_migration" in result.actions_proposed
    assert result.llm_cost_usd == pytest.approx(0.0042)
    assert result.error is None
    # Inject was published.
    assert any(t == "simulator.inject" for t, _ in bus.publishes)


async def test_run_one_missed_detection_returns_undetected() -> None:
    scenario = _gpu_ecc_scenario()
    bus = _ScriptedBus(scripted={})   # no scripted events
    result = await run_one(scenario, bus, detection_timeout_s=0.3, grace_s=0.1)
    assert result.detected is False
    assert result.detection_latency_sec is None
    assert result.rca_top1_match is False


async def test_run_one_partial_detection_no_rca() -> None:
    scenario = _gpu_ecc_scenario()
    bus = _ScriptedBus(
        scripted={
            "predictions.failure": [
                {
                    "site_id": "frankfurt",
                    "failure_kind": "gpu_ecc_runaway",
                    "probability": 0.9,
                },
            ],
            # No incident report → no RCA match.
        }
    )
    result = await run_one(scenario, bus, detection_timeout_s=2.0, grace_s=0.3)
    assert result.detected is True
    assert result.rca_top1_match is False
    assert result.llm_cost_usd == 0.0


async def test_run_one_publishes_inject_with_scenario_steps() -> None:
    scenario = _gpu_ecc_scenario()
    bus = _ScriptedBus()
    await run_one(scenario, bus, detection_timeout_s=0.3, grace_s=0.1)
    inject = next(p for t, p in bus.publishes if t == "simulator.inject")
    assert inject["scenario_name"] == "gpu_ecc_failure"
    assert inject["steps"]
    assert inject["steps"][0]["failure_mode"] == "gpu_ecc_runaway"

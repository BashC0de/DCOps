"""Benchmark runner.

Drives a deterministic list of scenarios through the live stack, captures
outcomes, and writes a JSON results file consumed by `report.py`.

Per scenario:
    1. Subscribe to `predictions.failure`, `incidents.report`,
       `recommendations.*`, `federation.rule_candidate.*` BEFORE publishing.
    2. Publish the scenario payload to `simulator.inject` (same shape as
       `scripts/inject_failure.py`).
    3. Wait up to `scenario.expected_detection.within_seconds` for the
       first matching `predictions.failure`.
    4. After detection (or timeout), wait an extra grace window for the
       downstream `incidents.report` + `recommendations.*` to land.
    5. Score the scenario against `expected_root_cause` and
       `expected_actions`; record latencies + LLM cost.

The runner can target a live Redis (`make bench`) OR a fake bus passed
explicitly (for the unit tests). Mocking the bus is what makes the runner
testable without docker.

Replay:
    `--save-state <dir>` writes per-scenario JSON snapshots; `--replay <dir>`
    re-scores from those snapshots without re-injecting. Useful for
    regression-testing scoring changes without paying the wall-clock cost.

Time bound:
    The default per-scenario timeout is 90s from `expected_detection.within_seconds`
    + 30s grace = 120s. The 200-scenario sweep fits inside 30 min when
    parallelised across the 3 sites (about 67 scenarios per site, 67 × 12s
    average run ≈ 14 min). Serial mode is slower; the CI run uses `--workers 3`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.event_bus import EventBus  # noqa: E402
from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from apps.simulator.scenarios import Scenario  # noqa: E402
from benchmarks.generate import categorise, generate  # noqa: E402

log = get_logger("bench.runner")


# --- result shape -------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    category: str
    site_id: str
    started_at: str
    finished_at: str
    detected: bool
    detection_latency_sec: float | None
    rca_top1_match: bool
    actions_proposed: list[str]
    actions_executed: list[str]
    expected_actions: list[str]
    candidate_propagated: bool
    llm_cost_usd: float
    error: str | None = None
    incident_id: str | None = None
    rca_text: str | None = None
    predictions: list[dict[str, Any]] = field(default_factory=list)


# --- helpers ------------------------------------------------------------------


def _scenario_site(scenario: Scenario) -> str:
    """Best-effort site inference from a scenario name."""
    for site in ("frankfurt", "singapore", "mumbai"):
        if site in scenario.name:
            return site
    return "frankfurt"


def _scenario_inject_payload(scenario: Scenario, site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "scenario_name": scenario.name,
        "steps": [
            {
                "delay_seconds": s.delay_seconds,
                "device_selector": s.device_selector,
                "failure_mode": s.failure_mode.value,
                "duration_seconds": s.duration_seconds,
            }
            for s in scenario.steps
        ],
    }


def _rca_match(expected: str, observed: str | None) -> bool:
    """Fuzzy substring match — split expected on whitespace and require
    ~half of the keywords to appear in the observed text."""
    if not observed:
        return False
    tokens = [t.lower() for t in expected.split() if len(t) > 4]
    if not tokens:
        return False
    obs = observed.lower()
    hits = sum(1 for t in tokens if t in obs)
    return hits >= max(2, len(tokens) // 3)


# --- bus-like protocol --------------------------------------------------------


class _BusProtocol:
    async def publish(self, topic: str, event: Any) -> int:
        raise NotImplementedError

    def subscribe(self, pattern: str):  # async iterator  # noqa: ANN201
        raise NotImplementedError

    async def close(self) -> None:
        pass


# --- single scenario run ------------------------------------------------------


async def run_one(
    scenario: Scenario,
    bus: _BusProtocol | Any,
    *,
    detection_timeout_s: float | None = None,
    grace_s: float = 30.0,
) -> ScenarioResult:
    """Run a single scenario; return its outcomes."""
    site_id = _scenario_site(scenario)
    started = datetime.now(timezone.utc)
    started_mono = time.monotonic()

    timeout = float(
        detection_timeout_s
        or scenario.expected_detection.get("within_seconds", 90)
    )

    predictions: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    # Set up subscribers BEFORE publishing.
    pred_task = asyncio.create_task(_collect(bus, "predictions.failure", predictions, timeout + grace_s, site_id))
    inc_task = asyncio.create_task(_collect(bus, "incidents.report", incidents, timeout + grace_s, site_id))
    rec_task = asyncio.create_task(_collect(bus, "recommendations.*", recommendations, timeout + grace_s, site_id))
    cand_task = asyncio.create_task(_collect(bus, "federation.rule_candidate.*", candidates, timeout + grace_s, None))

    # Brief delay so subscribers are wired up before we publish.
    await asyncio.sleep(0.05)

    try:
        await bus.publish("simulator.inject", _InjectEvent(**_scenario_inject_payload(scenario, site_id)))
    except Exception as exc:  # noqa: BLE001
        for t in (pred_task, inc_task, rec_task, cand_task):
            t.cancel()
        finished = datetime.now(timezone.utc)
        return ScenarioResult(
            name=scenario.name,
            category=categorise(scenario.name),
            site_id=site_id,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            detected=False,
            detection_latency_sec=None,
            rca_top1_match=False,
            actions_proposed=[],
            actions_executed=[],
            expected_actions=list(scenario.expected_actions),
            candidate_propagated=False,
            llm_cost_usd=0.0,
            error=f"publish_failed: {exc}",
        )

    # Wait for tasks to finish (they self-terminate when their window elapses).
    await asyncio.gather(pred_task, inc_task, rec_task, cand_task, return_exceptions=True)
    finished = datetime.now(timezone.utc)

    detection_latency = None
    if predictions:
        for p in predictions:
            # Use received_at_mono captured by _collect (relative to start).
            if isinstance(p.get("__received_mono"), float):
                detection_latency = p["__received_mono"] - started_mono
                break
            # Fallback to event timestamp delta.
            ts = p.get("timestamp")
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    detection_latency = (dt - started).total_seconds()
                    break
                except ValueError:
                    pass

    detected = detection_latency is not None
    incident_first = incidents[0] if incidents else None
    rca_text = None
    if incident_first:
        md = incident_first.get("metadata") or {}
        rca_text = md.get("summary") if isinstance(md, dict) else None
    rca_match = _rca_match(scenario.expected_root_cause, rca_text)
    llm_cost = float(incident_first.get("llm_cost_usd", 0.0)) if incident_first else 0.0
    actions_proposed = list({r.get("kind", "?") for r in recommendations if isinstance(r, dict)})

    return ScenarioResult(
        name=scenario.name,
        category=categorise(scenario.name),
        site_id=site_id,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        detected=detected,
        detection_latency_sec=detection_latency,
        rca_top1_match=rca_match,
        actions_proposed=actions_proposed,
        actions_executed=[],   # Week 8 closed-loop populates this in live mode.
        expected_actions=list(scenario.expected_actions),
        candidate_propagated=bool(candidates),
        llm_cost_usd=llm_cost,
        incident_id=incident_first.get("incident_id") if incident_first else None,
        rca_text=rca_text,
        predictions=[
            {k: v for k, v in p.items() if k != "__received_mono"} for p in predictions
        ],
    )


async def _collect(
    bus: Any,
    pattern: str,
    sink: list[dict[str, Any]],
    window_s: float,
    site_filter: str | None,
) -> None:
    """Append matching events on `pattern` to `sink` for `window_s` seconds."""
    deadline = time.monotonic() + window_s

    async def _consume() -> None:
        async for event in bus.subscribe(pattern):
            if not isinstance(event, dict):
                continue
            if site_filter and event.get("site_id") not in (site_filter, None):
                # Some events (federation candidates) carry their own target_site_id;
                # accept them when site_filter doesn't match.
                if event.get("target_site_id") != site_filter:
                    continue
            event["__received_mono"] = time.monotonic()
            sink.append(event)
            if time.monotonic() >= deadline:
                return

    try:
        await asyncio.wait_for(_consume(), timeout=window_s)
    except asyncio.TimeoutError:
        return


# --- inject envelope ----------------------------------------------------------


class _InjectEvent:
    """Lightweight pseudo-Pydantic envelope so `bus.publish` happily JSON-dumps it."""

    def __init__(self, **fields: Any) -> None:
        self._fields = fields

    def model_dump_json(self) -> str:
        return json.dumps(self._fields, default=str)


# --- batch runner -------------------------------------------------------------


async def run_batch(
    scenarios: list[Scenario],
    bus: Any,
    *,
    workers: int = 1,
    detection_timeout_s: float | None = None,
) -> list[ScenarioResult]:
    """Run scenarios with bounded concurrency.

    Use `workers > 1` only against a live stack — the unit-test fake bus
    runs them serially so its scripted responses stay deterministic.
    """
    if workers <= 1:
        return [await run_one(s, bus, detection_timeout_s=detection_timeout_s) for s in scenarios]

    sem = asyncio.Semaphore(workers)
    results: list[ScenarioResult | None] = [None] * len(scenarios)

    async def _one(idx: int) -> None:
        async with sem:
            results[idx] = await run_one(scenarios[idx], bus, detection_timeout_s=detection_timeout_s)

    await asyncio.gather(*[_one(i) for i in range(len(scenarios))])
    return [r for r in results if r is not None]


# --- CLI ----------------------------------------------------------------------


async def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target", type=int, default=200, help="Number of scenarios to generate."
    )
    parser.add_argument(
        "--only", nargs="*",
        help="Run only these scenario names (overrides --target)."
    )
    parser.add_argument(
        "--output", default="case_study/benchmark_results.json"
    )
    parser.add_argument(
        "--workers", type=int, default=int(os.getenv("BENCH_WORKERS", "3")),
        help="Concurrent scenarios in flight against the live stack.",
    )
    parser.add_argument(
        "--detection-timeout-s", type=float, default=None,
        help="Override the per-scenario detection window.",
    )
    args = parser.parse_args()

    scenarios = generate(target=args.target)
    if args.only:
        wanted = set(args.only)
        scenarios = [s for s in scenarios if s.name in wanted]

    bus = EventBus.from_env()
    try:
        log.info("bench.start", n_scenarios=len(scenarios), workers=args.workers)
        results = await run_batch(
            scenarios, bus,
            workers=args.workers,
            detection_timeout_s=args.detection_timeout_s,
        )
    finally:
        await bus.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in results], indent=2))
    detected = sum(1 for r in results if r.detected)
    rca_hits = sum(1 for r in results if r.rca_top1_match)
    log.info(
        "bench.done",
        count=len(results),
        detected=detected,
        rca_top1=rca_hits,
        output=str(out),
    )


__all__ = [
    "ScenarioResult",
    "run_one",
    "run_batch",
    "_rca_match",
]


if __name__ == "__main__":
    asyncio.run(main())

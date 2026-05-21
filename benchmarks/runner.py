"""Benchmark runner.

Drives a list of scenarios through the live stack, captures the outcomes,
and writes a JSON results file consumed by `report.py`.

Ships: Week 11 (see ROADMAP.md). This skeleton lays out the contract.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from apps.simulator.scenarios import list_available, load  # noqa: E402

log = get_logger("bench.runner")


@dataclass
class ScenarioResult:
    name: str
    started_at: str
    finished_at: str
    detected: bool
    detection_latency_sec: float | None
    rca_top1_match: bool
    actions_proposed: list[str]
    llm_cost_usd: float
    error: str | None = None


async def run_one(name: str) -> ScenarioResult:
    """Run a single scenario and capture the result."""
    started = datetime.now(timezone.utc)
    log.info("bench.run", scenario=name)
    scenario = load(name)
    _ = scenario     # TODO(week-11): dispatch via inject_failure script, watch bus for outcomes.
    finished = datetime.now(timezone.utc)
    return ScenarioResult(
        name=name,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        detected=False,                       # TODO(week-11)
        detection_latency_sec=None,
        rca_top1_match=False,
        actions_proposed=[],
        llm_cost_usd=0.0,
        error="not_implemented",
    )


async def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="case_study/benchmark_results.json")
    parser.add_argument("--only", nargs="*", help="Run only these scenarios.")
    args = parser.parse_args()

    names = args.only or list_available()
    results = [await run_one(n) for n in names]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in results], indent=2))
    log.info("bench.done", count=len(results), output=str(out))


if __name__ == "__main__":
    asyncio.run(main())

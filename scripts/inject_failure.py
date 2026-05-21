"""CLI for triggering a benchmark scenario through the physics engine.

Usage:
    python scripts/inject_failure.py --scenario gpu_ecc_failure --site frankfurt

In Week 3+ this dispatches via the bus topic `simulator.inject` so the
running simulator applies the failure live. Week 1 stub: prints the
scenario YAML it would have applied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redis.asyncio as redis  # noqa: E402

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402
from apps.simulator.scenarios import list_available, load  # noqa: E402

log = get_logger("inject_failure")


async def dispatch(site: str, scenario_name: str) -> None:
    scenario = load(scenario_name)
    log.info("inject.loaded", scenario=scenario.name, steps=len(scenario.steps))

    payload = {
        "site_id": site,
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

    client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        subscribers = await client.publish("simulator.inject", json.dumps(payload))
        log.info("inject.dispatched", subscribers=subscribers)
        if subscribers == 0:
            log.warning(
                "inject.no_subscribers",
                note="The simulator may not be running yet. Start it with `make dev`.",
            )
    finally:
        await client.aclose()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Inject a benchmark scenario into a site.")
    parser.add_argument("--scenario", required=True, help="Scenario name (no .yml extension).")
    parser.add_argument("--site", required=True, help="Site id, e.g. 'frankfurt'.")
    parser.add_argument("--list", action="store_true", help="List available scenarios and exit.")
    args = parser.parse_args()

    if args.list:
        for name in list_available():
            print(name)
        return

    asyncio.run(dispatch(args.site, args.scenario))


if __name__ == "__main__":
    main()

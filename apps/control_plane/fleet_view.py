"""Fleet view materializer.

Purpose:
    Aggregates per-site health summaries into a single fleet-level snapshot
    cached in Redis under `fleet:snapshot`. The dashboard reads this for
    the home view.

Ships: Week 9 (gRPC ingestion); Week 10 dashboard read path.
"""

from __future__ import annotations

import asyncio

from apps.agents.shared.logging import get_logger

log = get_logger(__name__)


async def run_fleet_view() -> None:
    """Long-running aggregator. Skeleton until Week 9."""
    log.info("control_plane.fleet_view.start", note="skeleton — aggregator ships Week 9")
    while True:
        # TODO(week-9): pull latest site heartbeats from `site:<id>:heartbeat`,
        #               materialize fleet snapshot, write to `fleet:snapshot`.
        await asyncio.sleep(5)


__all__ = ["run_fleet_view"]

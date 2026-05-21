"""Cross-site correlator.

Purpose:
    When site A's Sentinel learns a high-confidence detection rule, the
    correlator pushes it to sites B and C as a "candidate" rule. Each
    receiving site enables it in shadow mode for 48h before active use.

Ships: Week 9 (see ROADMAP.md).
"""

from __future__ import annotations

import asyncio

from apps.agents.shared.logging import get_logger

log = get_logger(__name__)


async def run_correlator() -> None:
    """Long-running cross-site rule propagator. Skeleton until Week 9."""
    log.info("control_plane.correlator.start", note="skeleton — propagation ships Week 9")
    while True:
        # TODO(week-9): subscribe to per-site `rules.discovered` events,
        #               score candidates, broadcast to other sites with
        #               shadow_until = now + 48h.
        await asyncio.sleep(15)


__all__ = ["run_correlator"]

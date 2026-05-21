"""Control plane entry point.

Boots three coroutines:
    - gRPC server for site → control-plane streams
    - fleet view materializer
    - cross-site correlator

Ships: Week 1 (skeleton); each subsystem fleshed out in Weeks 8-9.
"""

from __future__ import annotations

import asyncio

from apps.agents.shared.logging import configure_logging, get_logger
from apps.control_plane.cross_site_correlator import run_correlator
from apps.control_plane.fleet_view import run_fleet_view
from apps.control_plane.policy_engine import PolicyEngine

log = get_logger(__name__)


async def serve_grpc() -> None:
    """gRPC server for site streams. Skeleton until Week 9."""
    log.info("control_plane.grpc.start", note="skeleton — full server ships Week 9")
    # TODO(week-9): start grpc.aio.server() with handlers from apps/api/grpc/.
    while True:
        await asyncio.sleep(60)


async def main() -> None:
    configure_logging()
    log.info("control_plane.start")
    policy = PolicyEngine.from_default_config()
    log.info("control_plane.policy.loaded", policies=len(policy.policies))

    await asyncio.gather(
        serve_grpc(),
        run_fleet_view(),
        run_correlator(),
    )


if __name__ == "__main__":
    asyncio.run(main())

"""Audit sink service entrypoint."""

from __future__ import annotations

import asyncio

from apps.agents.shared.logging import configure_logging
from apps.audit.sink import run


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()

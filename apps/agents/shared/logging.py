"""Structured logging configuration.

Purpose:
    Single source of truth for structlog setup. Every agent and service
    imports `get_logger()` from here so log records have a consistent
    shape (JSON in prod, pretty-printed in dev).

Ships: Week 1 (see ROADMAP.md).

Convention:
    Every log record carries at minimum: timestamp, level, logger,
    site_id (if set in env), agent (if set by the caller). Audit-relevant
    records additionally carry: event_type, input_hash, output_hash,
    llm_cost_usd, confidence, trace_id.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_site_id(_: Any, __: Any, event_dict: EventDict) -> EventDict:
    """Attach SITE_ID from the environment so every log line is site-tagged."""
    site = os.getenv("SITE_ID")
    if site and "site_id" not in event_dict:
        event_dict["site_id"] = site
    return event_dict


def configure_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: Log level name (DEBUG/INFO/WARN/ERROR). Defaults to LOG_LEVEL env or INFO.
        json_output: If True, emit JSON; if False, pretty console. Defaults to
            JSON when not attached to a TTY (i.e. in containers).
    """
    log_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    use_json = json_output if json_output is not None else not sys.stderr.isatty()

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_site_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if use_json:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging into structlog so library messages flow through too.
    logging.basicConfig(format="%(message)s", level=getattr(logging, log_level), stream=sys.stderr)


def get_logger(name: str, **bind: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound logger with optional pre-bound fields (e.g. agent name)."""
    return structlog.get_logger(name).bind(**bind)


__all__ = ["configure_logging", "get_logger"]

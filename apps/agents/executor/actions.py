"""Executor action handlers.

Each handler maps a `Recommendation.kind` to an HTTP call against the
mock vendor service (which in production would be the real Redfish /
DCGM endpoint). Returns a `(ok, response_payload)` tuple.

Handlers don't update agent state — that's the Executor's job. They
just describe how to perform one kind of action.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from apps.agents.shared.events import Recommendation
from apps.agents.shared.logging import get_logger

log = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 10.0
ActionResult = tuple[bool, dict[str, Any]]
ActionHandler = Callable[[Recommendation, str], Awaitable[ActionResult]]


def _mocks_base_url() -> str | None:
    return os.getenv("MOCKS_BASE_URL")


async def _post_action(path: str, payload: dict[str, Any]) -> ActionResult:
    base = _mocks_base_url()
    if not base:
        return False, {"error": "MOCKS_BASE_URL not configured"}
    url = f"{base.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return True, resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("executor.action_http_failed", url=url, error=str(exc))
        return False, {"error": str(exc)}


# --- per-kind handlers ----------------------------------------------------------


async def handle_workload_migration(
    rec: Recommendation, action_id: str
) -> ActionResult:
    moves = rec.parameters.get("moves") or []
    payload = {
        "action_id": action_id,
        "recommendation_id": str(rec.recommendation_id),
        "moves": moves,
    }
    return await _post_action("/actions/migrate_workload", payload)


async def handle_fan_speed(
    rec: Recommendation, action_id: str
) -> ActionResult:
    devs = rec.target_device_ids
    if not devs:
        return False, {"error": "no target device for fan adjust"}
    payload = {
        "action_id": action_id,
        "recommendation_id": str(rec.recommendation_id),
        "device_id": devs[0],
        "target_fan_percent": float(rec.parameters.get("target_fan_percent", 80)),
    }
    return await _post_action("/actions/fan_speed_adjust", payload)


async def revert(
    original_action_id: str,
    *,
    reason: str,
) -> ActionResult:
    """Revert a previously-executed action."""
    payload = {
        "original_action_id": original_action_id,
        "reason": reason,
    }
    return await _post_action("/actions/revert", payload)


HANDLERS: dict[str, ActionHandler] = {
    "workload_migration": handle_workload_migration,
    "fan_speed_adjust":   handle_fan_speed,
}


def resolve(kind: str) -> ActionHandler | None:
    return HANDLERS.get(kind)


__all__ = [
    "ActionHandler",
    "ActionResult",
    "HANDLERS",
    "handle_fan_speed",
    "handle_workload_migration",
    "resolve",
    "revert",
]

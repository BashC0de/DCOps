"""Shared HTTP helper for the per-source normalizers.

Each normalizer poll cycle uses a single short-lived `httpx.AsyncClient`.
If the configured base URL is missing OR the request fails, the helper
returns `None` and the caller yields nothing — the ingestion service
keeps running regardless of mock/vendor availability.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from apps.agents.shared.logging import get_logger

log = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 5.0


def base_url() -> str | None:
    """Resolve the mocks base URL.

    Looks at:
      MOCKS_BASE_URL                — preferred single env var (set by `mocks` profile)
      Per-source overrides         — REDFISH_BASE_URL, DCGM_BASE_URL, etc.
                                      (read by normalizer modules directly when present)
    Returns None when nothing is configured — the normalizer yields nothing.
    """
    return os.getenv("MOCKS_BASE_URL")


async def get_json(url: str, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict[str, Any] | None:
    """GET `url` and parse JSON. Returns None on any error."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("ingestion.http.get_failed", url=url, error=str(exc))
        return None


async def get_text(url: str, timeout_s: float = _DEFAULT_TIMEOUT_S) -> str | None:
    """GET `url` and return text body. Returns None on any error."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:  # noqa: BLE001
        log.debug("ingestion.http.get_failed", url=url, error=str(exc))
        return None

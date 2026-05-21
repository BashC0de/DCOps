"""Smoke test for the API health endpoint. Requires `make dev` to be up."""

from __future__ import annotations

import os

import httpx
import pytest


@pytest.mark.integration
async def test_api_health_ok() -> None:
    base = os.getenv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8080")
    async with httpx.AsyncClient(base_url=base, timeout=5.0) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

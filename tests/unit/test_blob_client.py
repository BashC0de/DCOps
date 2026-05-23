"""Tests for the BlobStore (MinIO) wrapper — graceful degradation only.

Live MinIO interaction is exercised by integration tests; these tests
verify the unconnected client behaves safely.
"""

from __future__ import annotations

import pytest

from apps.agents.shared.blob_client import BlobStore

pytestmark = pytest.mark.unit


async def test_blob_disabled_until_connect() -> None:
    blob = BlobStore.from_env()
    assert blob.enabled is False
    assert await blob.ensure_bucket("anything") is False
    assert await blob.put_bytes("b", "k", b"data") is False
    assert await blob.get_bytes("b", "k") is None
    assert await blob.head("b", "k") is None


async def test_blob_close_is_safe_when_unconnected() -> None:
    blob = BlobStore.from_env()
    await blob.close()

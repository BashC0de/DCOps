"""Async wrapper around the ChromaDB HTTP client.

ChromaDB's Python SDK is sync. We wrap the small set of methods our agents
need with `asyncio.to_thread` so they don't block the event loop.

Connection details from env vars (`CHROMA_HOST`, `CHROMA_PORT`).

Graceful degradation:
    `from_env()` always succeeds. `connect()` returns False when the
    server is unreachable; `enabled` reflects connection state. Methods
    that need the server return safe defaults when disabled.

Used by:
    - Forensic — incident exemplars (`dcops_incidents`) + LLM response cache
    - Operator — runbook chunks (`dcops_runbooks`) + LLM response cache
    - Vision   — LLM response cache
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from chromadb.api import ClientAPI

log = get_logger(__name__)


class VectorStore:
    """Async wrapper around `chromadb.HttpClient`."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._client: ClientAPI | None = None

    @classmethod
    def from_env(cls) -> VectorStore:
        return cls(
            host=os.getenv("CHROMA_HOST", "chromadb"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
        )

    # --- lifecycle ------------------------------------------------------------

    async def connect(self) -> bool:
        """Open the Chroma client. Returns True on success."""
        if self._client is not None:
            return True
        try:
            import chromadb
        except ImportError:
            log.warning("vector.import_failed", note="`chromadb` package not installed")
            return False
        try:
            self._client = await asyncio.to_thread(
                chromadb.HttpClient, host=self._host, port=self._port
            )
            # Heartbeat to confirm the server is actually up.
            await asyncio.to_thread(self._client.heartbeat)
        except Exception as exc:  # noqa: BLE001
            log.warning("vector.connect_failed", host=self._host, port=self._port, error=str(exc))
            self._client = None
            return False
        log.info("vector.connected", host=self._host, port=self._port)
        return True

    async def close(self) -> None:
        # chromadb.HttpClient doesn't expose an explicit close — drop the ref.
        self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> ClientAPI | None:
        """Direct access for `SemanticCache` / `FewShotRetriever` constructors."""
        return self._client

    # --- high-level helpers ---------------------------------------------------

    async def get_or_create_collection(self, name: str) -> Any | None:
        """Return a collection handle, or None when disabled."""
        if self._client is None:
            return None
        try:
            return await asyncio.to_thread(self._client.get_or_create_collection, name=name)
        except Exception as exc:  # noqa: BLE001
            log.warning("vector.collection_failed", name=name, error=str(exc))
            return None


__all__ = ["VectorStore"]

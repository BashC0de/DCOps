"""Async MinIO/S3 wrapper.

Built on the official `minio` Python SDK (sync). We wrap the handful of
methods our services need with `asyncio.to_thread` so they don't block.

Connection details from env vars (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
`MINIO_SECRET_KEY`, `MINIO_BUCKET_RAW`, `MINIO_BUCKET_ARTIFACTS`).

Graceful degradation:
    `from_env()` always succeeds. `connect()` returns False when the
    server is unreachable. Methods that need the store return safe
    defaults when disabled.

Used by:
    - Audit sink — drains `audit.events` Redis stream into the
      artifacts bucket, keyed by SHA-256 hash of the payload.
    - Future: ingestion buffer overflow → MinIO replay (Week 8).
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import TYPE_CHECKING, Any

from apps.agents.shared.logging import get_logger

if TYPE_CHECKING:
    from minio import Minio

log = get_logger(__name__)


class BlobStore:
    """Async wrapper around the sync MinIO client."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._client: Minio | None = None

    @classmethod
    def from_env(cls) -> BlobStore:
        return cls(
            endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "dcops_minio"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "changeme_minio"),
            secure=os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
        )

    # --- lifecycle ------------------------------------------------------------

    async def connect(self) -> bool:
        if self._client is not None:
            return True
        try:
            from minio import Minio
        except ImportError:
            log.warning("blob.import_failed", note="`minio` package not installed")
            return False
        try:
            client = await asyncio.to_thread(
                Minio,
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )
            # list_buckets is the cheapest "are you up" check; raises on bad creds/down.
            await asyncio.to_thread(client.list_buckets)
            self._client = client
        except Exception as exc:  # noqa: BLE001
            log.warning("blob.connect_failed", endpoint=self._endpoint, error=str(exc))
            self._client = None
            return False
        log.info("blob.connected", endpoint=self._endpoint)
        return True

    async def close(self) -> None:
        # The sync MinIO client has no explicit close; drop the ref.
        self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # --- operations -----------------------------------------------------------

    async def ensure_bucket(self, bucket: str) -> bool:
        """Create `bucket` if it doesn't already exist."""
        if self._client is None:
            return False
        try:
            exists = await asyncio.to_thread(self._client.bucket_exists, bucket)
            if not exists:
                await asyncio.to_thread(self._client.make_bucket, bucket)
                log.info("blob.bucket_created", bucket=bucket)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("blob.ensure_bucket_failed", bucket=bucket, error=str(exc))
            return False

    async def put_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """Upload `data` to `s3://bucket/key`."""
        if self._client is None:
            return False
        try:
            await asyncio.to_thread(
                self._client.put_object,
                bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
                metadata=metadata or {},
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("blob.put_failed", bucket=bucket, key=key, error=str(exc))
            return False

    async def get_bytes(self, bucket: str, key: str) -> bytes | None:
        """Fetch object bytes. Returns None on miss or error."""
        if self._client is None:
            return None
        try:
            resp = await asyncio.to_thread(self._client.get_object, bucket, key)
            try:
                return await asyncio.to_thread(resp.read)
            finally:
                await asyncio.to_thread(resp.close)
                await asyncio.to_thread(resp.release_conn)
        except Exception as exc:  # noqa: BLE001
            log.debug("blob.get_failed", bucket=bucket, key=key, error=str(exc))
            return None

    async def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        """Return object metadata if it exists. None on miss."""
        if self._client is None:
            return None
        try:
            stat = await asyncio.to_thread(self._client.stat_object, bucket, key)
            return {"size": stat.size, "etag": stat.etag, "last_modified": stat.last_modified}
        except Exception:  # noqa: BLE001 — miss is the common case
            return None


__all__ = ["BlobStore"]

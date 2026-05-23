"""Audit-stream → MinIO consumer.

Reads the `audit.events` Redis Stream using a consumer group, writes each
payload to MinIO under `audit/<YYYY>/<MM>/<DD>/<sha256>.json`, then acks
the message. On MinIO outage the message is left un-acked and will be
retried by the consumer group.

Idempotency: the object key is content-addressed (SHA-256 of payload), so
re-delivery overwrites with identical content.

Run via the `audit` service in docker-compose (dev/demo profiles).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from apps.agents.shared.blob_client import BlobStore
from apps.agents.shared.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "audit.events"
DEFAULT_GROUP = "audit-sink"
DEFAULT_BUCKET = os.getenv("MINIO_BUCKET_ARTIFACTS", "dcops-artifacts")
KEY_PREFIX = "audit"


def _consumer_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _object_key(payload: bytes, ts: datetime | None = None) -> str:
    digest = sha256(payload).hexdigest()
    ts = ts or datetime.now(timezone.utc)
    return f"{KEY_PREFIX}/{ts:%Y/%m/%d}/{digest}.json"


async def _ensure_group(redis_client: Any, stream: str, group: str) -> None:
    """Create the consumer group at $ if it doesn't exist."""
    try:
        await redis_client.xgroup_create(stream, group, id="$", mkstream=True)
        log.info("audit.group_created", stream=stream, group=group)
    except Exception as exc:  # noqa: BLE001
        # BUSYGROUP — group already exists; ignore.
        if "BUSYGROUP" in str(exc):
            return
        raise


async def _process_entry(
    redis_client: Any,
    blob: BlobStore,
    *,
    bucket: str,
    group: str,
    msg_id: Any,
    fields: Any,
) -> bool:
    """Process one stream entry. Returns True iff blob.put + ack succeeded.

    Pulled out for unit testing — exercises the full happy/failure paths
    without needing to drive an xreadgroup loop under fakeredis.
    """
    payload = fields.get("data", "") if isinstance(fields, dict) else ""
    if not payload:
        await redis_client.xack(STREAM_KEY, group, msg_id)
        return True
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    ok = await blob.put_bytes(
        bucket,
        _object_key(body),
        body,
        content_type="application/json",
        metadata={"stream-entry-id": str(msg_id)},
    )
    if ok:
        await redis_client.xack(STREAM_KEY, group, msg_id)
        return True
    log.warning("audit.put_failed_no_ack", entry_id=str(msg_id))
    return False


async def _consume_loop(
    redis_client: Any,
    blob: BlobStore,
    *,
    bucket: str,
    group: str,
    consumer: str,
    block_ms: int,
    batch: int,
) -> None:
    """Long-running read-loop. Thin shell around `_process_entry`."""
    while True:
        try:
            entries = await redis_client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={STREAM_KEY: ">"},
                count=batch,
                block=block_ms,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("audit.read_failed", error=str(exc))
            await asyncio.sleep(2.0)
            continue

        if not entries:
            continue

        for _, msgs in entries:
            for msg_id, fields in msgs:
                await _process_entry(
                    redis_client, blob,
                    bucket=bucket, group=group,
                    msg_id=msg_id, fields=fields,
                )


async def run(
    *,
    redis_url: str | None = None,
    group: str = DEFAULT_GROUP,
    bucket: str = DEFAULT_BUCKET,
    batch: int = 64,
    block_ms: int = 5000,
) -> None:
    """Service entry point.

    Connects to Redis + MinIO, ensures the consumer group + bucket exist,
    and enters the consume loop.
    """
    import redis.asyncio as redis  # local import keeps the module fakeredis-friendly

    url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
    client = redis.from_url(url, decode_responses=True)

    blob = BlobStore.from_env()
    ok = await blob.connect()
    if not ok:
        log.warning("audit.blob_unavailable", note="will keep retrying on each put")
    else:
        await blob.ensure_bucket(bucket)

    consumer = _consumer_name()
    await _ensure_group(client, STREAM_KEY, group)
    log.info(
        "audit.sink.start",
        stream=STREAM_KEY,
        group=group,
        consumer=consumer,
        bucket=bucket,
    )

    try:
        await _consume_loop(
            client,
            blob,
            bucket=bucket,
            group=group,
            consumer=consumer,
            block_ms=block_ms,
            batch=batch,
        )
    finally:
        await client.aclose()
        await blob.close()


__all__ = [
    "run",
    "_consume_loop",
    "_process_entry",
    "_object_key",
    "_ensure_group",
    "STREAM_KEY",
    "DEFAULT_GROUP",
]

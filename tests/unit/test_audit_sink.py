"""Tests for the audit-stream → MinIO sink.

Uses fakeredis to back the stream and a tiny in-memory `_FakeBlob`. The
full `_consume_loop` runs `xreadgroup` in a tight loop which fakeredis
doesn't reliably block on, so we test `_process_entry` directly — that's
where the actual business logic lives. The loop is a thin shell around it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import fakeredis.aioredis
import pytest

from apps.audit.sink import (
    DEFAULT_GROUP,
    STREAM_KEY,
    _ensure_group,
    _object_key,
    _process_entry,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeBlob:
    fail_next: bool = False
    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)

    async def put_bytes(self, bucket: str, key: str, data: bytes, **_: Any) -> bool:
        if self.fail_next:
            self.fail_next = False
            return False
        self.objects[(bucket, key)] = data
        return True


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def test_object_key_is_content_addressed() -> None:
    payload = b'{"x": 1}'
    k1 = _object_key(payload)
    k2 = _object_key(payload)
    assert k1 == k2
    assert k1.startswith("audit/")
    assert k1.endswith(".json")
    k3 = _object_key(b'{"x": 2}')
    assert k1 != k3


async def test_ensure_group_creates_once(redis_client) -> None:
    await _ensure_group(redis_client, STREAM_KEY, DEFAULT_GROUP)
    # Second call must be a no-op (BUSYGROUP swallowed).
    await _ensure_group(redis_client, STREAM_KEY, DEFAULT_GROUP)


async def test_process_entry_writes_and_acks(redis_client) -> None:
    blob = _FakeBlob()
    await _ensure_group(redis_client, STREAM_KEY, DEFAULT_GROUP)
    payload = json.dumps({"agent": "forensic", "task_class": "rca"})
    msg_id = await redis_client.xadd(STREAM_KEY, {"data": payload})

    # Take the message ourselves so the group is the owner.
    raw = await redis_client.xreadgroup(
        groupname=DEFAULT_GROUP,
        consumername="t",
        streams={STREAM_KEY: ">"},
        count=1,
    )
    _, msgs = raw[0]
    msg_id, fields = msgs[0]

    ok = await _process_entry(
        redis_client, blob,
        bucket="dcops-artifacts", group=DEFAULT_GROUP,
        msg_id=msg_id, fields=fields,
    )
    assert ok is True
    assert len(blob.objects) == 1
    (_, key), data = next(iter(blob.objects.items()))
    assert key.startswith("audit/") and key.endswith(".json")
    assert data.decode() == payload

    info = await redis_client.xpending(STREAM_KEY, DEFAULT_GROUP)
    pending = info["pending"] if isinstance(info, dict) else info[0]
    assert pending == 0


async def test_process_entry_skips_ack_on_blob_failure(redis_client) -> None:
    blob = _FakeBlob(fail_next=True)
    await _ensure_group(redis_client, STREAM_KEY, DEFAULT_GROUP)
    await redis_client.xadd(STREAM_KEY, {"data": "payload"})
    raw = await redis_client.xreadgroup(
        groupname=DEFAULT_GROUP,
        consumername="t",
        streams={STREAM_KEY: ">"},
        count=1,
    )
    _, msgs = raw[0]
    msg_id, fields = msgs[0]

    ok = await _process_entry(
        redis_client, blob,
        bucket="b", group=DEFAULT_GROUP,
        msg_id=msg_id, fields=fields,
    )
    assert ok is False
    assert blob.objects == {}
    info = await redis_client.xpending(STREAM_KEY, DEFAULT_GROUP)
    pending = info["pending"] if isinstance(info, dict) else info[0]
    assert pending == 1


async def test_process_entry_empty_payload_acks_without_writing(redis_client) -> None:
    blob = _FakeBlob()
    await _ensure_group(redis_client, STREAM_KEY, DEFAULT_GROUP)
    await redis_client.xadd(STREAM_KEY, {"data": ""})
    raw = await redis_client.xreadgroup(
        groupname=DEFAULT_GROUP,
        consumername="t",
        streams={STREAM_KEY: ">"},
        count=1,
    )
    _, msgs = raw[0]
    msg_id, fields = msgs[0]

    ok = await _process_entry(
        redis_client, blob,
        bucket="b", group=DEFAULT_GROUP,
        msg_id=msg_id, fields=fields,
    )
    assert ok is True
    assert blob.objects == {}
    info = await redis_client.xpending(STREAM_KEY, DEFAULT_GROUP)
    pending = info["pending"] if isinstance(info, dict) else info[0]
    assert pending == 0

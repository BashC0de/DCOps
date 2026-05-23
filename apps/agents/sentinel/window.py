"""Per-device sliding window of telemetry events.

Sentinel needs short-horizon history to compute features like "ECC rate
last 5 min" and "thermal slope last 60 s". Each device gets a small
fixed-capacity ring buffer keyed by `device_id`.

The window holds parsed dicts (the bus yields raw dicts), bounded by both
count (`maxlen`) and age (`max_age_s`). Stale entries are evicted at read
time so the buffer never grows unbounded across long-lived agents.

Memory model:
    Default 256 events × 1 KB/event × ~3000 devices/site = ~750 MB worst
    case. The 16 GB laptop budget for Sentinel is 768 MB (see
    ARCHITECTURE.md § Memory budget) so the defaults below cap at 128
    events to leave headroom for XGBoost.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


DEFAULT_MAXLEN = int(os.getenv("SENTINEL_WINDOW_MAXLEN", "128"))
DEFAULT_MAX_AGE_S = float(os.getenv("SENTINEL_WINDOW_MAX_AGE_S", "300"))


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


class DeviceWindow:
    """Bounded ring of telemetry dicts for one device.

    Use `add(event)` to ingest; `recent()` to read with stale entries
    already evicted. `recent_for_metric(name)` filters down to a single
    canonical metric for feature builders.
    """

    __slots__ = ("device_id", "_buf", "_max_age_s")

    def __init__(
        self,
        device_id: str,
        maxlen: int = DEFAULT_MAXLEN,
        max_age_s: float = DEFAULT_MAX_AGE_S,
    ) -> None:
        self.device_id = device_id
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._max_age_s = max_age_s

    def add(self, event: dict[str, Any]) -> None:
        self._buf.append(event)

    def _evict_stale(self) -> None:
        if not self._buf:
            return
        cutoff = datetime.now(timezone.utc).timestamp() - self._max_age_s
        while self._buf:
            first = self._buf[0]
            ts = _parse_ts(first.get("timestamp"))
            if ts is None:
                self._buf.popleft()
                continue
            if ts.timestamp() >= cutoff:
                return
            self._buf.popleft()

    def recent(self) -> list[dict[str, Any]]:
        self._evict_stale()
        return list(self._buf)

    def recent_for_metric(self, metric: str) -> list[dict[str, Any]]:
        return [e for e in self.recent() if e.get("metric") == metric]

    def __len__(self) -> int:
        self._evict_stale()
        return len(self._buf)


class WindowStore:
    """Map of `device_id` → `DeviceWindow`.

    Keeps everything in memory. The expected fleet on a single site is
    ~3K devices; with 128-event windows this stays comfortably inside
    the 768 MB Sentinel cap.
    """

    def __init__(
        self,
        maxlen: int = DEFAULT_MAXLEN,
        max_age_s: float = DEFAULT_MAX_AGE_S,
    ) -> None:
        self._maxlen = maxlen
        self._max_age_s = max_age_s
        self._windows: dict[str, DeviceWindow] = {}

    def ingest(self, event: dict[str, Any]) -> str | None:
        device_id = event.get("device_id")
        if not isinstance(device_id, str):
            return None
        w = self._windows.get(device_id)
        if w is None:
            w = DeviceWindow(device_id, maxlen=self._maxlen, max_age_s=self._max_age_s)
            self._windows[device_id] = w
        w.add(event)
        return device_id

    def device_ids(self) -> Iterable[str]:
        return list(self._windows.keys())

    def get(self, device_id: str) -> DeviceWindow | None:
        return self._windows.get(device_id)

    def total_events(self) -> int:
        return sum(len(w) for w in self._windows.values())

    def __len__(self) -> int:
        return len(self._windows)


__all__ = ["DeviceWindow", "WindowStore"]

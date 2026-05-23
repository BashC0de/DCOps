"""NVIDIA DCGM normalizer.

Scrapes the DCGM Prometheus exporter and converts canonical NVIDIA GPU
metrics into TelemetryEvent records. Also surfaces XID codes — Sentinel
uses these for rule-based detection of GPU failures.

In dev, the in-repo mocks service at `${MOCKS_BASE_URL}/metrics/dcgm`
serves Prometheus-format exposition. Against real hardware, point
`DCGM_EXPORTER_URL` at the DCGM exporter (`/metrics`).

Ships: Week 2 (real scraping against the mocks profile).
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator

from apps.agents.shared.logging import get_logger
from apps.ingestion.normalizers._http import base_url, get_text
from apps.ingestion.schema import CanonicalMetric, DeviceType, Severity, TelemetryEvent

log = get_logger(__name__)

# DCGM metric name → canonical mapping.
_METRIC_MAP: dict[str, CanonicalMetric] = {
    "DCGM_FI_DEV_GPU_TEMP":     CanonicalMetric.GPU_TEMP_CELSIUS,
    "DCGM_FI_DEV_POWER_USAGE":  CanonicalMetric.GPU_POWER_WATTS,
    "DCGM_FI_DEV_GPU_UTIL":     CanonicalMetric.GPU_UTIL_PERCENT,
    "DCGM_FI_DEV_FB_USED":      CanonicalMetric.GPU_MEM_USED_BYTES,
    "DCGM_FI_DEV_XID_ERRORS":   CanonicalMetric.GPU_XID_CODE,
}

_UNIT_MAP: dict[CanonicalMetric, str] = {
    CanonicalMetric.GPU_TEMP_CELSIUS:    "celsius",
    CanonicalMetric.GPU_POWER_WATTS:     "watts",
    CanonicalMetric.GPU_UTIL_PERCENT:    "percent",
    CanonicalMetric.GPU_MEM_USED_BYTES:  "MiB",  # DCGM reports framebuffer in MiB
    CanonicalMetric.GPU_XID_CODE:        "count",
}

# `name{label1="val1",label2="val2"} value` — Prometheus text format.
_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>[^}]*)\})?\s+"
    r"(?P<value>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')


def _root() -> str | None:
    explicit = os.getenv("DCGM_EXPORTER_URL")
    if explicit:
        return explicit  # full URL including /metrics path
    bu = base_url()
    return f"{bu}/metrics/dcgm" if bu else None


def _site() -> str:
    return os.getenv("SITE_ID", "unknown")


def _hall_rack(device_id: str) -> tuple[str, str]:
    parts = device_id.split("-")
    if len(parts) >= 4 and parts[1].startswith("h") and parts[2].startswith("r"):
        return f"{parts[0]}-{parts[1]}", f"{parts[0]}-{parts[1]}-{parts[2]}"
    return "unknown", "unknown"


def _parse_labels(s: str | None) -> dict[str, str]:
    return dict(_LABEL_RE.findall(s)) if s else {}


async def poll() -> AsyncIterator[TelemetryEvent]:
    url = _root()
    if not url:
        return
    body = await get_text(url)
    if not body:
        return

    site = _site()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        metric_name = m.group("name")
        canonical = _METRIC_MAP.get(metric_name)
        if canonical is None:
            continue
        labels = _parse_labels(m.group("labels"))
        gpu_id = labels.get("gpu") or labels.get("UUID") or labels.get("device")
        if not gpu_id:
            continue
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        hall_id, rack_id = _hall_rack(gpu_id)
        severity = Severity.INFO
        if canonical is CanonicalMetric.GPU_XID_CODE and value > 0:
            severity = Severity.CRITICAL  # any non-zero XID is bad news
        yield TelemetryEvent(
            site_id=site,
            hall_id=hall_id,
            rack_id=rack_id,
            device_id=gpu_id,
            device_type=DeviceType.GPU,
            metric=canonical,
            value=value,
            unit=_UNIT_MAP.get(canonical),
            severity=severity,
            metadata={"source": "dcgm", "exporter_metric": metric_name, **labels},
        )

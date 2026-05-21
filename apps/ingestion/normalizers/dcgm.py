"""NVIDIA DCGM normalizer.

Purpose:
    Scrapes the DCGM Prometheus exporter (`/metrics` endpoint) and converts
    the canonical NVIDIA GPU metrics into TelemetryEvent records. Also
    surfaces XID codes, which Sentinel uses for rule-based detection.

Ships: Week 2 (stub); real scraping Week 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from apps.ingestion.schema import TelemetryEvent


async def poll() -> AsyncIterator[TelemetryEvent]:
    """Yield DCGM-sourced telemetry events. No-op until Week 3."""
    # TODO(week-3): scrape DCGM exporter at $DCGM_EXPORTER_URL and parse with prometheus_client.
    if False:
        yield None  # type: ignore[misc]
    return

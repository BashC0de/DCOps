"""Tests for the per-source telemetry normalizers.

Each normalizer is exercised against an in-process `apps.mocks` FastAPI
TestClient via `httpx.MockTransport`, so no real network is involved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.ingestion.normalizers import dcgm, env, ipmi, redfish, snmp
from apps.ingestion.schema import CanonicalMetric, DeviceType, TelemetryEvent
from apps.mocks.main import app

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _set_mocks_url(monkeypatch) -> None:
    # Tests run with a base URL pointing at a localhost-ish address; the
    # `httpx.AsyncClient` inside the normalizers is monkey-patched per-test
    # to use the FastAPI TestClient via a custom transport.
    monkeypatch.setenv("MOCKS_BASE_URL", "http://mocks-test")
    monkeypatch.setenv("SITE_ID", "frankfurt")


@pytest.fixture
def fastapi_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def patch_httpx(monkeypatch, fastapi_client) -> None:
    """Replace httpx.AsyncClient with one that routes through the FastAPI app."""
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path
        # Re-issue against the in-process FastAPI app using the sync TestClient.
        sub = fastapi_client.request(method, path)
        return httpx.Response(
            status_code=sub.status_code,
            headers={"content-type": sub.headers.get("content-type", "application/json")},
            content=sub.content,
        )

    transport = httpx.MockTransport(_handler)

    orig_init = httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):  # noqa: ANN001, ANN201
        kwargs.setdefault("transport", transport)
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


# --- redfish --------------------------------------------------------------------

async def test_redfish_yields_temp_fan_power_events(patch_httpx) -> None:
    events: list[TelemetryEvent] = []
    async for e in redfish.poll():
        events.append(e)
    assert events, "redfish.poll() should yield events when mocks endpoint is up"

    metrics = {e.metric for e in events}
    assert CanonicalMetric.CPU_TEMP_CELSIUS in metrics
    assert CanonicalMetric.FAN_RPM in metrics
    assert CanonicalMetric.POWER_DRAW_WATTS in metrics
    assert all(e.device_type == DeviceType.SERVER for e in events)


async def test_redfish_yields_nothing_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("MOCKS_BASE_URL", raising=False)
    monkeypatch.delenv("REDFISH_BASE_URL", raising=False)
    events = [e async for e in redfish.poll()]
    assert events == []


# --- dcgm -----------------------------------------------------------------------

async def test_dcgm_parses_prometheus_text(patch_httpx) -> None:
    events = [e async for e in dcgm.poll()]
    assert events
    metrics = {e.metric for e in events}
    assert CanonicalMetric.GPU_TEMP_CELSIUS in metrics
    assert CanonicalMetric.GPU_POWER_WATTS in metrics
    assert all(e.device_type == DeviceType.GPU for e in events)


async def test_dcgm_yields_nothing_when_url_unset(monkeypatch) -> None:
    monkeypatch.delenv("MOCKS_BASE_URL", raising=False)
    monkeypatch.delenv("DCGM_EXPORTER_URL", raising=False)
    events = [e async for e in dcgm.poll()]
    assert events == []


# --- snmp -----------------------------------------------------------------------

async def test_snmp_yields_switch_and_pdu_events(patch_httpx) -> None:
    events = [e async for e in snmp.poll()]
    assert events
    types = {e.device_type for e in events}
    assert DeviceType.SWITCH in types
    assert DeviceType.PDU in types
    # Sanity: at least one bytes-in event and one PDU load event.
    assert any(e.metric == CanonicalMetric.NET_BPS_IN for e in events)
    assert any(e.metric == CanonicalMetric.PDU_LOAD_PERCENT for e in events)


# --- ipmi -----------------------------------------------------------------------

async def test_ipmi_emits_cpu_temp_and_fans(patch_httpx) -> None:
    events = [e async for e in ipmi.poll()]
    metrics = {e.metric for e in events}
    assert CanonicalMetric.CPU_TEMP_CELSIUS in metrics
    assert CanonicalMetric.FAN_RPM in metrics
    assert CanonicalMetric.POWER_DRAW_WATTS in metrics


# --- env ------------------------------------------------------------------------

async def test_env_emits_inlet_outlet_humidity(patch_httpx) -> None:
    events = [e async for e in env.poll()]
    metrics = {e.metric for e in events}
    assert CanonicalMetric.ENV_INLET_CELSIUS in metrics
    assert CanonicalMetric.ENV_OUTLET_CELSIUS in metrics
    assert CanonicalMetric.ENV_HUMIDITY_PERCENT in metrics

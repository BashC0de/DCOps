"""Smoke tests for the in-repo mock vendor service."""

from __future__ import annotations

import pytest

from apps.mocks.main import app
from apps.mocks.topology import MockTopology, build_topology

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def test_health(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_redfish_systems_listing(client) -> None:
    r = client.get("/redfish/v1/Systems")
    assert r.status_code == 200
    data = r.json()
    assert data["Members@odata.count"] > 0
    assert all(m["@odata.id"].startswith("/redfish/v1/Systems/") for m in data["Members"])


def test_redfish_system_detail_and_thermal_and_power(client) -> None:
    listing = client.get("/redfish/v1/Systems").json()
    first_id = listing["Members"][0]["@odata.id"].rsplit("/", 1)[-1]

    sys = client.get(f"/redfish/v1/Systems/{first_id}")
    assert sys.status_code == 200
    assert sys.json()["Id"] == first_id

    thermal = client.get(f"/redfish/v1/Chassis/{first_id}/Thermal").json()
    assert thermal["Temperatures"]
    assert thermal["Fans"]

    power = client.get(f"/redfish/v1/Chassis/{first_id}/Power").json()
    assert power["PowerControl"][0]["PowerConsumedWatts"] > 0


def test_redfish_unknown_returns_404(client) -> None:
    assert client.get("/redfish/v1/Systems/does-not-exist").status_code == 404


def test_dcgm_metrics_is_prometheus_text(client) -> None:
    r = client.get("/metrics/dcgm")
    assert r.status_code == 200
    body = r.text
    assert "DCGM_FI_DEV_GPU_TEMP" in body
    assert "DCGM_FI_DEV_POWER_USAGE" in body
    # Should contain at least one parseable sample line.
    sample_lines = [line for line in body.splitlines() if line and not line.startswith("#")]
    assert sample_lines


def test_snmp_walk_includes_switches_and_pdus(client) -> None:
    data = client.get("/snmp/walk").json()
    dtypes = {d["device_type"] for d in data["devices"]}
    assert "switch" in dtypes
    assert "pdu" in dtypes


def test_ipmi_sensors_present(client) -> None:
    data = client.get("/ipmi/sensors").json()
    assert data["devices"]
    first = data["devices"][0]
    assert any(s["metric"] == "cpu.temp.celsius" for s in first["sensors"])


def test_env_sensors_carry_canonical_metric_names(client) -> None:
    data = client.get("/env/sensors").json()
    metrics = {s["metric"] for s in data["sensors"]}
    assert "env.inlet.celsius" in metrics
    assert "env.outlet.celsius" in metrics


def test_topology_deterministic_across_calls() -> None:
    a = build_topology("frankfurt")
    b = build_topology("frankfurt")
    assert [d.id for d in a.devices] == [d.id for d in b.devices]


def test_topology_devices_have_expected_shape() -> None:
    topo: MockTopology = build_topology("frankfurt")
    types = {d.type for d in topo.devices}
    assert {"server", "pdu", "switch", "crac"} <= types

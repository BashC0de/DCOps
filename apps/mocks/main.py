"""FastAPI mock vendor service.

One process, multiple endpoints — Redfish, DCGM (Prometheus), SNMP, IPMI,
env. Each returns a deterministic but time-varying value so the
normalizers produce non-trivial telemetry without RNG flakiness.

Run via the `mocks` docker-compose profile. The normalizers read
`MOCKS_BASE_URL` from env to find this service.

Endpoints
---------
GET /health
GET /redfish/v1/Systems                       # list of servers
GET /redfish/v1/Systems/{id}                  # server detail
GET /redfish/v1/Chassis/{id}/Thermal          # temps + fans
GET /redfish/v1/Chassis/{id}/Power            # PowerConsumedWatts
GET /metrics/dcgm                             # Prometheus DCGM exposition
GET /snmp/walk                                # switch + PDU OIDs as JSON
GET /ipmi/sensors                             # IPMI sensor table
GET /env/sensors                              # facility inlet/outlet/humidity
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException

from apps.mocks.topology import MockDevice, MockTopology, build_topology

app = FastAPI(title="DCOps mocks", version="0.2.0")

_SITE_ID = os.getenv("SITE_ID", "frankfurt")
_TOPOLOGY: MockTopology = build_topology(_SITE_ID)


# --- helpers --------------------------------------------------------------------

def _wave(amplitude: float, period_s: float, phase: float = 0.0) -> float:
    """Smooth sine variation around 0 so values look plausible."""
    return amplitude * math.sin(2 * math.pi * (time.time() / period_s) + phase)


def _server_temp_c(device_id: str) -> float:
    phase = (hash(device_id) & 0xFFFF) / 0xFFFF * math.tau
    return 62.0 + _wave(amplitude=4.0, period_s=120.0, phase=phase)


def _gpu_temp_c(device_id: str) -> float:
    phase = (hash(device_id) & 0xFFFF) / 0xFFFF * math.tau
    return 68.0 + _wave(amplitude=6.0, period_s=80.0, phase=phase)


def _gpu_power_w(device_id: str) -> float:
    phase = (hash(device_id) & 0xFFFF) / 0xFFFF * math.tau
    return 380.0 + _wave(amplitude=120.0, period_s=60.0, phase=phase)


def _server_power_w(device_id: str) -> float:
    phase = (hash(device_id) & 0xFFFF) / 0xFFFF * math.tau
    return 480.0 + _wave(amplitude=80.0, period_s=90.0, phase=phase)


def _inlet_c() -> float:
    return 22.0 + _wave(amplitude=2.5, period_s=300.0)


def _outlet_c() -> float:
    return 31.0 + _wave(amplitude=3.0, period_s=300.0, phase=math.pi / 4)


def _humidity_pct() -> float:
    return 45.0 + _wave(amplitude=10.0, period_s=600.0)


# --- routes --------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "site_id": _SITE_ID,
        "n_devices": len(_TOPOLOGY.devices),
    }


# --- Action endpoints (Executor target; in-memory action log) ------------------

_ACTION_LOG: list[dict[str, Any]] = []


@app.get("/actions/log")
async def actions_log(limit: int = 100) -> dict[str, Any]:
    """Inspect what the Executor has done. Used by tests + the dashboard."""
    return {"actions": _ACTION_LOG[-limit:]}


@app.post("/actions/migrate_workload")
async def action_migrate_workload(payload: dict[str, Any]) -> dict[str, Any]:
    """Move workloads between racks. Returns a synthetic success envelope."""
    moves = payload.get("moves") or []
    if not isinstance(moves, list):
        raise HTTPException(status_code=400, detail="moves must be a list")
    record = {
        "kind": "migrate_workload",
        "ts": time.time(),
        "n_moves": len(moves),
        "payload": payload,
        "status": "ok",
    }
    _ACTION_LOG.append(record)
    return {"status": "ok", "n_moves": len(moves), "action_id": payload.get("action_id")}


@app.post("/actions/fan_speed_adjust")
async def action_fan_speed_adjust(payload: dict[str, Any]) -> dict[str, Any]:
    target_device_id = payload.get("device_id")
    target_pct = payload.get("target_fan_percent")
    if not isinstance(target_device_id, str) or not isinstance(target_pct, (int, float)):
        raise HTTPException(status_code=400, detail="device_id + target_fan_percent required")
    record = {
        "kind": "fan_speed_adjust",
        "ts": time.time(),
        "device_id": target_device_id,
        "target_fan_percent": float(target_pct),
        "payload": payload,
        "status": "ok",
    }
    _ACTION_LOG.append(record)
    return {"status": "ok", "applied": True, "action_id": payload.get("action_id")}


@app.post("/actions/revert")
async def action_revert(payload: dict[str, Any]) -> dict[str, Any]:
    """Generic revert. Records the original action_id being undone."""
    original_action_id = payload.get("original_action_id")
    if not isinstance(original_action_id, str):
        raise HTTPException(status_code=400, detail="original_action_id required")
    record = {
        "kind": "revert",
        "ts": time.time(),
        "reverted_action_id": original_action_id,
        "payload": payload,
        "status": "ok",
    }
    _ACTION_LOG.append(record)
    return {"status": "ok", "reverted_action_id": original_action_id}


# --- Redfish --------------------------------------------------------------------

@app.get("/redfish/v1/Systems")
async def redfish_list_systems() -> dict[str, Any]:
    servers = _TOPOLOGY.by_type("server")
    return {
        "@odata.id": "/redfish/v1/Systems",
        "Name": "Computer System Collection",
        "Members@odata.count": len(servers),
        "Members": [
            {"@odata.id": f"/redfish/v1/Systems/{d.id}"} for d in servers
        ],
    }


def _require_device(device_id: str, type_: str | None = None) -> MockDevice:
    d = _TOPOLOGY.by_id(device_id)
    if d is None or (type_ is not None and d.type != type_):
        raise HTTPException(status_code=404, detail=f"unknown {type_ or 'device'}: {device_id}")
    return d


@app.get("/redfish/v1/Systems/{device_id}")
async def redfish_system(device_id: str) -> dict[str, Any]:
    d = _require_device(device_id, "server")
    return {
        "@odata.id": f"/redfish/v1/Systems/{d.id}",
        "Id": d.id,
        "Name": d.id,
        "Manufacturer": d.vendor,
        "Model": d.model,
        "PowerState": "On",
        "Status": {"Health": "OK", "State": "Enabled"},
        "ProcessorSummary": {"Count": 2, "Model": "Intel Xeon Platinum"},
        "MemorySummary": {"TotalSystemMemoryGiB": 512, "Status": {"Health": "OK"}},
        "Links": {"Chassis": [{"@odata.id": f"/redfish/v1/Chassis/{d.id}"}]},
    }


@app.get("/redfish/v1/Chassis/{device_id}/Thermal")
async def redfish_thermal(device_id: str) -> dict[str, Any]:
    d = _require_device(device_id, "server")
    base_t = _server_temp_c(d.id)
    return {
        "@odata.id": f"/redfish/v1/Chassis/{d.id}/Thermal",
        "Temperatures": [
            {"Name": "CPU 1 Temp", "ReadingCelsius": round(base_t, 1),
             "Status": {"Health": "OK"}, "PhysicalContext": "CPU"},
            {"Name": "CPU 2 Temp", "ReadingCelsius": round(base_t - 1.5, 1),
             "Status": {"Health": "OK"}, "PhysicalContext": "CPU"},
            {"Name": "Inlet Temp", "ReadingCelsius": round(_inlet_c(), 1),
             "Status": {"Health": "OK"}, "PhysicalContext": "Intake"},
        ],
        "Fans": [
            {"Name": "Fan 1", "Reading": int(4200 + _wave(150, 30, hash(d.id))),
             "ReadingUnits": "RPM", "Status": {"Health": "OK"}},
            {"Name": "Fan 2", "Reading": int(4150 + _wave(150, 30, hash(d.id) + 1)),
             "ReadingUnits": "RPM", "Status": {"Health": "OK"}},
        ],
    }


@app.get("/redfish/v1/Chassis/{device_id}/Power")
async def redfish_power(device_id: str) -> dict[str, Any]:
    d = _require_device(device_id, "server")
    watts = round(_server_power_w(d.id), 1)
    return {
        "@odata.id": f"/redfish/v1/Chassis/{d.id}/Power",
        "PowerControl": [
            {
                "Name": "System Power Control",
                "PowerConsumedWatts": watts,
                "PowerCapacityWatts": 1000.0,
                "Status": {"Health": "OK"},
            }
        ],
        "PowerSupplies": [
            {
                "Name": "PS1 Status",
                "PowerOutputWatts": round(watts * 0.5, 1),
                "EfficiencyPercent": 93.5 + _wave(0.4, 600, hash(d.id)),
                "Status": {"Health": "OK"},
            },
            {
                "Name": "PS2 Status",
                "PowerOutputWatts": round(watts * 0.5, 1),
                "EfficiencyPercent": 93.5 + _wave(0.4, 600, hash(d.id) + 1),
                "Status": {"Health": "OK"},
            },
        ],
    }


# --- DCGM (Prometheus text exposition) ------------------------------------------

@app.get("/metrics/dcgm", response_class=None)
async def dcgm_metrics() -> Any:
    """Prometheus DCGM exposition. Returns text/plain."""
    from fastapi.responses import PlainTextResponse

    gpus = _TOPOLOGY.by_type("gpu")
    lines: list[str] = [
        "# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C).",
        "# TYPE DCGM_FI_DEV_GPU_TEMP gauge",
    ]
    for g in gpus:
        lines.append(
            f'DCGM_FI_DEV_GPU_TEMP{{gpu="{g.id}",modelName="{g.model}"}} '
            f"{_gpu_temp_c(g.id):.2f}"
        )
    lines += [
        "# HELP DCGM_FI_DEV_POWER_USAGE GPU power usage in watts.",
        "# TYPE DCGM_FI_DEV_POWER_USAGE gauge",
    ]
    for g in gpus:
        lines.append(
            f'DCGM_FI_DEV_POWER_USAGE{{gpu="{g.id}",modelName="{g.model}"}} '
            f"{_gpu_power_w(g.id):.2f}"
        )
    lines += [
        "# HELP DCGM_FI_DEV_GPU_UTIL GPU utilization (in %).",
        "# TYPE DCGM_FI_DEV_GPU_UTIL gauge",
    ]
    for g in gpus:
        util = 70.0 + _wave(20.0, 45.0, hash(g.id))
        lines.append(
            f'DCGM_FI_DEV_GPU_UTIL{{gpu="{g.id}",modelName="{g.model}"}} {util:.1f}'
        )
    lines += [
        "# HELP DCGM_FI_DEV_XID_ERRORS Count of XID errors observed.",
        "# TYPE DCGM_FI_DEV_XID_ERRORS counter",
    ]
    for g in gpus:
        # Almost always zero; mock keeps it deterministically 0 for now.
        lines.append(f'DCGM_FI_DEV_XID_ERRORS{{gpu="{g.id}"}} 0')
    lines += [
        "# HELP DCGM_FI_DEV_FB_USED GPU framebuffer (mem) used in MiB.",
        "# TYPE DCGM_FI_DEV_FB_USED gauge",
    ]
    for g in gpus:
        used_mib = 32000 + int(_wave(5000, 60, hash(g.id)))
        lines.append(f'DCGM_FI_DEV_FB_USED{{gpu="{g.id}"}} {used_mib}')

    return PlainTextResponse("\n".join(lines) + "\n")


# --- SNMP-like JSON (switches + PDUs) ------------------------------------------

@app.get("/snmp/walk")
async def snmp_walk() -> dict[str, Any]:
    """Return an aggregated SNMP-style walk for all switches + PDUs."""
    devices: list[dict[str, Any]] = []
    for sw in _TOPOLOGY.by_type("switch"):
        bps_in = 1_000_000_000 + int(_wave(2e8, 30, hash(sw.id)))
        bps_out = 800_000_000 + int(_wave(2e8, 30, hash(sw.id) + 1))
        devices.append(
            {
                "device_id": sw.id,
                "device_type": "switch",
                "oids": {
                    "ifInOctets.1": bps_in,
                    "ifOutOctets.1": bps_out,
                    "ifInErrors.1": 0,
                    "ifOperStatus.1": 1,  # 1 = up
                    "ifHCInOctets.aggregate": bps_in * 48,
                },
            }
        )
    for pdu in _TOPOLOGY.by_type("pdu"):
        load_pct = 55.0 + _wave(15.0, 120.0, hash(pdu.id))
        devices.append(
            {
                "device_id": pdu.id,
                "device_type": "pdu",
                "oids": {
                    "rPDU2PhaseStatusLoadState.1": load_pct,
                    "rPDU2DeviceConfigName.1": pdu.model,
                },
            }
        )
    return {"devices": devices}


# --- IPMI sensor JSON ----------------------------------------------------------

@app.get("/ipmi/sensors")
async def ipmi_sensors() -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    for srv in _TOPOLOGY.by_type("server"):
        temp = _server_temp_c(srv.id)
        watts = _server_power_w(srv.id)
        devices.append(
            {
                "device_id": srv.id,
                "device_type": "server",
                "sensors": [
                    {"name": "CPU1 Temp", "metric": "cpu.temp.celsius",
                     "value": round(temp, 1), "unit": "celsius"},
                    {"name": "CPU2 Temp", "metric": "cpu.temp.celsius",
                     "value": round(temp - 1.5, 1), "unit": "celsius"},
                    {"name": "Fan1",      "metric": "fan.rpm",
                     "value": int(4200 + _wave(150, 30, hash(srv.id))), "unit": "RPM"},
                    {"name": "PowerDraw", "metric": "power.draw.watts",
                     "value": round(watts, 1), "unit": "watts"},
                    {"name": "PSU1Eff",   "metric": "psu.efficiency.percent",
                     "value": round(93.5 + _wave(0.4, 600, hash(srv.id)), 2), "unit": "percent"},
                ],
            }
        )
    return {"devices": devices}


# --- Facility env sensors ------------------------------------------------------

@app.get("/env/sensors")
async def env_sensors() -> dict[str, Any]:
    """Per-hall inlet/outlet/humidity and CRAC supply/return temps."""
    halls = sorted({d.hall_id for d in _TOPOLOGY.devices if d.hall_id})
    sensors: list[dict[str, Any]] = []
    for hall_id in halls:
        sensors.extend(
            [
                {"device_id": f"{hall_id}-sensor-inlet",
                 "device_type": "sensor",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "env.inlet.celsius",
                 "value": round(_inlet_c(), 2), "unit": "celsius"},
                {"device_id": f"{hall_id}-sensor-outlet",
                 "device_type": "sensor",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "env.outlet.celsius",
                 "value": round(_outlet_c(), 2), "unit": "celsius"},
                {"device_id": f"{hall_id}-sensor-humidity",
                 "device_type": "sensor",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "env.humidity.percent",
                 "value": round(_humidity_pct(), 2), "unit": "percent"},
                {"device_id": f"{hall_id}-crac1",
                 "device_type": "crac",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "crac.supply.celsius",
                 "value": round(_inlet_c() - 4, 2), "unit": "celsius"},
                {"device_id": f"{hall_id}-crac1",
                 "device_type": "crac",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "crac.return.celsius",
                 "value": round(_outlet_c() + 1, 2), "unit": "celsius"},
                {"device_id": f"{hall_id}-crac1",
                 "device_type": "crac",
                 "rack_id": "",
                 "hall_id": hall_id,
                 "metric": "crac.fan.percent",
                 "value": round(55.0 + _wave(8.0, 240, hash(hall_id)), 1),
                 "unit": "percent"},
            ]
        )
    return {"sensors": sensors}

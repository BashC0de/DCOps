# Week 2 — Mock vendor endpoints + real normalizers

> Drop this into a fresh Claude Code session to begin Week 2. The scaffold from `v0.1.0-scaffold` is the starting state.

## Goal

Replace the "simulator publishes directly to Redis" shortcut with a real ingestion path that goes through normalizers parsing vendor-shaped payloads.

Today (Week 1 end-state):

```
simulator → TelemetryEvent → Redis → agents
```

End of Week 2:

```
mock vendor endpoint → normalizer (HTTP/SNMP/IPMI client) → TelemetryEvent → Redis → agents
                                ▲
synthetic simulator ────────────┘  (for programmable failure scenarios; still publishes
                                    direct envelopes too — both coexist)
```

The point: prove the normalizers can parse the payload shapes real hardware emits. The synthetic simulator stays as the programmable failure source.

## Deliverables

1. **`mocks` compose profile** in [docker-compose.yml](../../docker-compose.yml) — runs alongside `dev`/`demo`. Containers:
   - `redfish-mock` — DMTF [Redfish-Mockup-Server](https://github.com/DMTF/Redfish-Mockup-Server) on `:8001`, serving a Dell iDRAC mockup (`Systems/`, `Chassis/`, `Power/`, `Thermal/`).
   - `dcgm-exporter` — NVIDIA's [dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter) in simulation mode on `:9400`, Prometheus exposition.
   - `ipmi-sim` — UDP 623, responding to `ipmitool sensor` commands. Use [ipmi-sim](https://github.com/cminyard/openipmi).
   - `snmpsim` — UDP 161, serving a recorded MIB walk (use [snmpsim-lextudio](https://github.com/lextudio/snmpsim)).
2. **Real normalizers** under [apps/ingestion/normalizers/](../../apps/ingestion/normalizers/). Each replaces its stub `async def poll()` with a real client:
   - `redfish.py` — httpx client, parses `Thermal/Temperatures` → `CPU_TEMP_CELSIUS`, `Power/PowerControl` → `POWER_DRAW_WATTS`, etc.
   - `dcgm.py` — fetches `/metrics`, parses Prometheus exposition, maps `DCGM_FI_DEV_GPU_TEMP` → `GPU_TEMP_CELSIUS`, `DCGM_FI_DEV_ECC_UNCORR_TOTAL` → `GPU_ECC_UNCORRECTABLE`, etc.
   - `ipmi.py` — subprocess `ipmitool sensor`; parse the tabular output.
   - `snmp.py` — `pysnmp` walk; map OIDs to `CanonicalMetric` via a small dispatch table.
3. **Ingestion service** [apps/ingestion/main.py](../../apps/ingestion/main.py) — runs all four normalizers concurrently, publishes the resulting events through the shared `EventBus`.
4. **TimescaleDB hypertable** — `apps/ingestion/timescale_writer.py` writes the same envelopes to the `telemetry` hypertable. DDL goes in [infra/timescale/](../../infra/timescale/) (init script).
5. **Tests**:
   - Unit: each normalizer gets a payload fixture (a captured response from its mock) and asserts the produced `TelemetryEvent` shape. Use `respx` for httpx mocks, fixture files for the rest.
   - Integration (marker `integration`): boot the `mocks` profile, run the ingestion service for ~10s, assert rows in TimescaleDB and topics in Redis.

## Success criteria

- `docker compose --profile mocks up` brings up all four mock servers in < 30s.
- `curl http://localhost:8001/redfish/v1/Systems/1` returns valid Redfish JSON.
- `curl http://localhost:9400/metrics | grep DCGM_FI_DEV_GPU_TEMP` returns at least one sample.
- With `dev` + `mocks` up, `redis-cli MONITOR | grep telemetry.gpu` shows events whose `metadata.source` is `dcgm` (not `simulator`).
- 5 minutes of runtime → > 100K rows in TimescaleDB across all four sources.
- `uv run pytest -m "not integration"` stays green.
- `uv run pytest -m integration` runs green when the dev profile is up.

## Non-goals

- No agent logic changes. They still just subscribe + log. Reasoning starts Week 4.
- No new `CanonicalMetric` values without a corresponding mock that emits them. Schema is frozen at the Week 1 set; add metrics in a separate PR if Week 2 surfaces a need.
- No retry/backoff sophistication. A normalizer that fails its poll just logs + skips that tick.

## Starting state to verify

```
git checkout v0.1.0-scaffold
make install
make test                # green
make up                  # data profile boots
```

If any of those fail on `main`, fix that first — don't build on top of a broken scaffold.

## Pointers

- Telemetry envelope: [apps/ingestion/schema.py](../../apps/ingestion/schema.py).
- Where to add the metric→canonical mapping: keep dispatch tables co-located with each normalizer; don't grow `schema.py`.
- Existing event bus pattern: [apps/agents/shared/event_bus.py](../../apps/agents/shared/event_bus.py) — typed publish; reuse.
- Roadmap context: [ROADMAP.md](../../ROADMAP.md) "Week 2".

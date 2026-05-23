# DCOps Copilot — Repository State

> Snapshot of what's real, what's stubbed, and what's next. Updated at the end of each week. The roadmap in [ROADMAP.md](ROADMAP.md) is the plan; this file is the receipts.

**Last updated:** 2026-05-22
**Phase:** 1 — Foundation
**Current week:** end of Week 1 → entering Week 2
**Tag:** `v0.1.0-scaffold`

---

## TL;DR

The repo is a complete, runnable Week-1 scaffold:

- All five data stores boot under `docker compose --profile data`.
- The `dev` profile additionally brings up one site of agents plus the dashboard.
- The simulator produces canonical `TelemetryEvent`s and publishes them straight to Redis.
- The Next.js dashboard builds and renders against the API.
- Unit tests pass; pre-commit, ruff, black, mypy are wired.

No telemetry yet flows through a real ingestion normalizer — the simulator bypasses them. No agent yet does real reasoning — they subscribe and log. That is the explicit Week 2/3 boundary.

---

## What works today

### Infrastructure
- [`docker-compose.yml`](docker-compose.yml) defines `data`, `dev`, `demo`, `site-1..3`, and `tools` profiles with explicit memory caps.
- TimescaleDB, Neo4j, ChromaDB, Redis, MinIO start with healthchecks.
- `make dev` / `make demo` / `make seed` targets in [Makefile](Makefile).

### Telemetry schema
- [apps/ingestion/schema.py](apps/ingestion/schema.py) — `TelemetryEvent` Pydantic model with the frozen `CanonicalMetric` enum (28 metrics across CPU, GPU, power, cooling, storage, network).
- `frozen=True`, `extra="forbid"`, timezone-aware timestamps enforced.

### Simulator
- [apps/simulator/main.py](apps/simulator/main.py) builds `DataHall` → `Server`/`GPU`/`PDU` objects from [sites.py](apps/simulator/sites.py) and [devices.py](apps/simulator/devices.py).
- Tick loop applies load modulation, runs power + thermal physics, emits `TelemetryEvent`s to Redis.
- Failure injection wired through the `simulator.inject` topic.

### Physics
- [apps/physics/power.py](apps/physics/power.py) and [apps/physics/thermal.py](apps/physics/thermal.py) implement first-pass models; [failure_injector.py](apps/physics/failure_injector.py) flips devices into named failure modes.

### Agents (skeletons only)
- All eight agent packages have a `main.py` that subscribes to its topic and logs received events. No reasoning yet.

### API
- FastAPI at [apps/api/main.py](apps/api/main.py); `/health` works. Other routes return placeholder data.

### Dashboard
- Next.js 14 app under [apps/dashboard/](apps/dashboard/). Builds and lints clean.

### Tests
- Unit tests in [tests/unit/](tests/unit/) cover event bus, failure injector, policy engine, telemetry schema.
- One integration test in [tests/integration/test_health.py](tests/integration/test_health.py).
- `make test` green on a clean clone.

### Quality gates
- [pyproject.toml](pyproject.toml) configures ruff, black, mypy strict, pytest with coverage.
- [.pre-commit-config.yaml](.pre-commit-config.yaml) blocks committing `.env`, runs ruff + prettier.
- [.github/workflows/ci.yml](.github/workflows/ci.yml) runs lint + unit tests + dashboard build + docker-compose config validation on every push and PR.

---

## What's stubbed

These files exist with the right shape so imports resolve and tests can target them, but the real logic ships in a later week.

| File | What it does today | When real |
|---|---|---|
| [apps/ingestion/normalizers/redfish.py](apps/ingestion/normalizers/redfish.py) | `async def poll()` → empty generator | Week 2 (mock iDRAC) → Week 3 (real HTTP) |
| [apps/ingestion/normalizers/dcgm.py](apps/ingestion/normalizers/dcgm.py) | same | Week 2 (dcgm-exporter sim) |
| [apps/ingestion/normalizers/ipmi.py](apps/ingestion/normalizers/ipmi.py) | same | Week 2 (ipmi-sim) |
| [apps/ingestion/normalizers/snmp.py](apps/ingestion/normalizers/snmp.py) | same | Week 2 (snmpsim) |
| [apps/ingestion/normalizers/env.py](apps/ingestion/normalizers/env.py) | same | Week 3 |
| [apps/agents/sentinel/](apps/agents/sentinel/) and the other seven agents | subscribe + log, no inference | Week 4+ |
| [apps/api/routes/](apps/api/routes/) | placeholders that return canned data | Week 3 (`/telemetry/recent`), Week 5+ (rest) |
| [apps/control_plane/](apps/control_plane/) | module layout only | Week 8 |
| [benchmarks/](benchmarks/) | runner shape only, no scenarios yet | Week 10 |

The current telemetry path bypasses the normalizers entirely:

```
simulator → TelemetryEvent → Redis → agents
```

Week 2's job is to make this path also exist:

```
mock vendor endpoint → normalizer → TelemetryEvent → Redis → agents
```

---

## How to verify

```bash
cp .env.example .env
make install            # uv sync + npm install + pre-commit install
make up                 # data profile only
make test               # unit tests (no docker required after install)
make dev                # data + one site of agents + dashboard
```

Then:

- `redis-cli MONITOR` should show `telemetry.*` traffic within ~10s.
- `curl localhost:8080/health` returns OK.
- `docker logs sentinel-frankfurt` shows received events.
- `http://localhost:3000` loads the dashboard shell.

---

## Next up — Week 2

**Theme:** real-shape telemetry envelopes.

1. Stand up mock vendor endpoints under a new `mocks` compose profile:
   - DMTF Redfish Mockup Server (Dell iDRAC schemas)
   - `dcgm-exporter` in simulation mode (NVIDIA GPU metrics, Prometheus format)
   - `ipmi-sim` on UDP 623
   - `snmpsim` with a recorded MIB walk
2. Turn the four `normalizers/*.py` stubs into real polling clients that emit `TelemetryEvent`s.
3. The synthetic simulator stays — it's the source of programmable failure scenarios. The mocks run alongside it for real-shape data.
4. Wire ingestion to TimescaleDB hypertables; verify > 100K rows after 5 min of runtime (Week 2 success criterion in [ROADMAP.md](ROADMAP.md)).

The prompt that drives Week 2 lives at [docs/prompts/week-2.md](docs/prompts/week-2.md).

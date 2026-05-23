# DCOps Copilot — Repository State

> Snapshot of what's real, what's stubbed, and what's next. Updated at the end of each week. The roadmap in [ROADMAP.md](ROADMAP.md) is the plan; this file is the receipts.

**Last updated:** 2026-05-23
**Phase:** 4 — Trust, Benchmarks, Polish **(code complete)**
**Current week:** Week 12 docs shipped; awaiting `make bench` + demo recording for v1.0.0
**Tag:** `v0.12.0-week-12`

---

## TL;DR

Week 12 closes out the code path for the 12-week build. [case_study/DRAFT.md](case_study/DRAFT.md) is now a real case study (capabilities table grounded in actual ship state, deployment story for the Ollama-default path + optional Anthropic backend, cost analysis, lessons learned, what-was-cut-and-why). [case_study/demo_script.md](case_study/demo_script.md) is updated for the OSS-default path with a recovery playbook for live moments. [case_study/metrics_template.md](case_study/metrics_template.md) is now 1:1 with the `make bench` HTML report shape. [case_study/release_checklist.md](case_study/release_checklist.md) lists the live-machine steps to v1.0.0 — train Sentinel (optional), run `make bench`, screenshot the dashboard, record the demo, tag.

**286 unit tests pass — no warnings, no exclusions.** Backend, dashboard, mocks, benchmarks, audit substrate, federation correlator, policy engine — all wired and tested.

---

## What works today

### Infrastructure
- [`docker-compose.yml`](docker-compose.yml) defines `data`, `dev`, `demo`, `site-1..3`, `tools`, and `mocks` profiles with explicit memory caps.
- TimescaleDB, Neo4j, ChromaDB, Redis, MinIO start with healthchecks.
- `ollama` service runs a local OSS LLM runtime; `ollama-init` warms `LLM_MODEL_FAST` / `_CODER` / `_REASONING` on first boot.
- `mocks` service serves Redfish + DCGM + SNMP + IPMI + env-sensor shapes (see [apps/mocks/main.py](apps/mocks/main.py)).
- `make dev` / `make demo` / `make seed` targets in [Makefile](Makefile).

### Telemetry schema
- [apps/ingestion/schema.py](apps/ingestion/schema.py) — `TelemetryEvent` Pydantic model with the frozen `CanonicalMetric` enum (28 metrics).
- `frozen=True`, `extra="forbid"`, timezone-aware timestamps enforced.

### Simulator
- [apps/simulator/main.py](apps/simulator/main.py) emits `TelemetryEvent`s to Redis with physics-driven load/thermal modulation. Failure injection wired through the `simulator.inject` topic.

### Physics
- [apps/physics/power.py](apps/physics/power.py), [apps/physics/thermal.py](apps/physics/thermal.py), [apps/physics/failure_injector.py](apps/physics/failure_injector.py) — first-pass models in place.

### Ingestion (Week 2)
- [apps/ingestion/main.py](apps/ingestion/main.py) runs five normalizer source pollers AND a TimescaleDB writer task that subscribes to `telemetry.*` and bulk-inserts (batch by count or interval).
- [apps/ingestion/normalizers/](apps/ingestion/normalizers/) — `redfish`, `dcgm`, `ipmi`, `snmp`, `env` are real HTTP polling clients now. They no-op gracefully when `MOCKS_BASE_URL` is unset OR the endpoint is unreachable.
- [apps/agents/shared/ts_client.py](apps/agents/shared/ts_client.py) — async psycopg pool with `insert_telemetry`, `recent_telemetry`, `execute_select` (refuses non-SELECT), `insert_incident`.

### Mock vendor endpoints (Week 2)
- [apps/mocks/main.py](apps/mocks/main.py) — single FastAPI service emulating four vendor schemas. Saved us four vendor-specific Docker images.
- [apps/mocks/topology.py](apps/mocks/topology.py) — deterministic device inventory per site.

### LLM stack (steps 1–3 + bucket 2)
- [apps/agents/shared/llm_router.py](apps/agents/shared/llm_router.py) — pluggable backend (Ollama default, Anthropic optional extra), audit stream publish to `audit.events`, daily-budget breach → fast-tier downgrade + `budget.exceeded` event.
- [apps/agents/shared/llm_backends/](apps/agents/shared/llm_backends/) — Ollama (httpx) and Anthropic backends.
- [apps/agents/shared/quality/](apps/agents/shared/quality/) — `structured` (JSON-schema decoding + retry), `self_consistency`, `verifier`, `kg_grounding`, `semantic_cache`, `few_shot`, `reranker`, `escalation`.
- [apps/agents/shared/quality/schemas.py](apps/agents/shared/quality/schemas.py) — `IncidentRCA`, `OperatorAnswer` (SELECT-only validator), `VisionFinding`.

### Shared DB clients (bucket 2 + Week 3)
- [apps/agents/shared/kg_client.py](apps/agents/shared/kg_client.py) — async Neo4j wrapper (`validate_device_ids`, `dependency_subgraph`, `register_incident`).
- [apps/agents/shared/vector_client.py](apps/agents/shared/vector_client.py) — async Chroma wrapper (HTTP, `to_thread`-wrapped).
- [apps/agents/shared/ts_client.py](apps/agents/shared/ts_client.py) — async TimescaleDB wrapper.
- [apps/agents/shared/blob_client.py](apps/agents/shared/blob_client.py) — async MinIO wrapper (Week 3).

All four clients graceful-degrade: methods become no-ops until `.connect()` succeeds.

### Audit substrate (Week 3)
- [apps/agents/shared/event_bus.py](apps/agents/shared/event_bus.py) `publish_stream()` is wired into the LLM router so every `CallRecord` lands on `audit.events`.
- [apps/audit/sink.py](apps/audit/sink.py) — consumer-group reader that drains `audit.events` and writes each payload to MinIO at `audit/<YYYY>/<MM>/<DD>/<sha256>.json`. Content-addressed (re-publishing is idempotent), per-message ack so failed writes are retried.
- New `dcops-audit` service runs in `dev`/`demo` profiles.

### API (Weeks 3–7)
- [apps/api/main.py](apps/api/main.py) lifespan constructs `TimescaleStore`, `KnowledgeGraph`, and `EventBus` and exposes them via `app.state.ts` / `app.state.kg` / `app.state.bus`.
- [apps/api/routes/telemetry.py](apps/api/routes/telemetry.py): `GET /telemetry/recent`, `GET /telemetry/range`.
- [apps/api/routes/incidents.py](apps/api/routes/incidents.py): `GET /incidents` + `GET /incidents/{id}`.
- [apps/api/routes/twin.py](apps/api/routes/twin.py): `GET /twin/state`.
- [apps/api/routes/agents.py](apps/api/routes/agents.py): `GET /agents/health` reads heartbeats from Redis.
- [apps/api/routes/query.py](apps/api/routes/query.py): `POST /query` round-trips through the Operator agent.
- [apps/api/routes/recommendations.py](apps/api/routes/recommendations.py): `GET /recommendations` + `GET /recommendations/{id}` from Optimizer's Redis list.
- [apps/api/routes/forecasts.py](apps/api/routes/forecasts.py): `GET /forecasts/{site}/{metric}?horizon_days=N` from Planner's Redis cache.
- All routes return `status="degraded"` (200, empty arrays) when their data plane is offline.

### Agents
- **Sentinel** — full predictive pipeline wired (Week 4):
  - [apps/agents/sentinel/window.py](apps/agents/sentinel/window.py) per-device sliding window (count + age bounded).
  - [apps/agents/sentinel/features.py](apps/agents/sentinel/features.py) per-metric mean/max/slope/count → stable feature vector.
  - [apps/agents/sentinel/rules.py](apps/agents/sentinel/rules.py) 7 deterministic rules (XID, ECC uncorrectable, ECC storm, GPU thermal, fan+hot-CPU, disk reallocated burst, PSU efficiency drop).
  - [apps/agents/sentinel/inference.py](apps/agents/sentinel/inference.py) XGBoost wrapper with model-missing fallback.
  - [apps/agents/sentinel/main.py](apps/agents/sentinel/main.py) — inference loop, rule + model fusion, dedupe window, publish `PredictedFailure`.
  - [scripts/train_sentinel.py](scripts/train_sentinel.py) — Backblaze SMART + synthetic GPU XID training pipeline; persists `data/models/sentinel.xgb`.
- **Optimizer** — full bin-packing pipeline wired (Week 7):
  - [apps/agents/optimizer/solver.py](apps/agents/optimizer/solver.py) — pure OR-Tools CP-SAT solver. Inputs: `Workload[]` + `Rack[]` + incident rack id. Constraints: PDU power cap, thermal headroom, HA-group anti-affinity. Objective: minimise post-move inlet stress + heavy penalty for placing workloads back on the incident rack. Time-bounded (default 10s).
  - [apps/agents/optimizer/main.py](apps/agents/optimizer/main.py) — subscribes to `incidents.report`, derives workloads from recent Timescale power draws, solves, publishes `Recommendation` on `recommendations.workload_migration`, persists JSON to Redis list `recommendations:recent`.
- **Planner** — full forecasting pipeline wired (Week 7):
  - [apps/agents/planner/forecaster.py](apps/agents/planner/forecaster.py) — Prophet wrapper with 80% CI envelopes; linear-extrapolation fallback when Prophet is missing or history is too short.
  - [apps/agents/planner/main.py](apps/agents/planner/main.py) — timer-driven (no bus subscription). Every hour, for each `(site, metric)` pair, pulls 30 days of daily aggregates from Timescale, fits Prophet, publishes `CapacityForecast` on `forecasts.<horizon>` for horizons 30/60/90, caches each at `forecasts:<site>:<metric>:<horizon>` in Redis (2h TTL).
- **Executor** — full closed-loop remediation (Week 8):
  - [apps/control_plane/policy_engine.py](apps/control_plane/policy_engine.py) — 4 policy kinds (`blast_radius`, `blackout_window`, `change_freeze`, `custom`), per-site overrides, precedence (DENIED > NEEDS_HUMAN > APPROVED), `evaluate()` returns `(decision, reason, applied_policy_ids)`.
  - [apps/agents/executor/actions.py](apps/agents/executor/actions.py) — action handlers per kind: `workload_migration`, `fan_speed_adjust`, plus a generic `revert()`. Each handler is an httpx POST against the mocks service.
  - [apps/agents/executor/main.py](apps/agents/executor/main.py) — full flow: policy gate → KPI snapshot from Timescale → handler call → publish `ActionExecuted` on `actions.executed` → persist to Redis list `actions:recent`. Denied recs are recorded too (audit trail). Needs-human recs publish on `actions.needs_human`.
- **Rollback Monitor** — KPI verification (Week 8):
  - [apps/agents/rollback/main.py](apps/agents/rollback/main.py) — for every `ActionExecuted`, schedules a delayed `_verify()` (`ROLLBACK_OBSERVATION_S`, default 300s). Snapshots the same KPIs the Executor recorded, computes per-metric regression with kind-aware direction (lower-is-better for temps, higher-is-better for fan RPM), triggers the mock revert + publishes `ActionRolledBack` on regression.

### Mock action endpoints (Week 8)
- [apps/mocks/main.py](apps/mocks/main.py) now serves `POST /actions/migrate_workload`, `POST /actions/fan_speed_adjust`, `POST /actions/revert`, and `GET /actions/log` (in-memory audit for tests + dashboard).
- **Forensic** — full LLM pipeline wired: cache → few-shot → schema-constrained call → verifier → KG-ground → persist + publish `IncidentReport`.
- **Operator** — full LLM pipeline + `_execute_sql` through read-only Timescale + Plotly chart spec.
- **Vision** — full multimodal pipeline + `IncidentVisionAddendum` publish; addendum now echoes `request_id` in metadata for API-side filtering.

### Cross-site federation (Week 9)
- [apps/control_plane/cross_site_correlator.py](apps/control_plane/cross_site_correlator.py) — `CrossSiteCorrelator` tracks `(origin_site, failure_kind)` hits with sliding-window decay and a confidence floor. When the threshold is crossed (default 3 hits ≥ 0.85 confidence within 1h), broadcasts a `RuleCandidate` to every other site in `FEDERATION_SITES`. Per-target cooldown prevents flapping. Each candidate carries `shadow_until = now + 48h` so receiving sites enable it in shadow mode.
- [apps/control_plane/fleet_view.py](apps/control_plane/fleet_view.py) — scans `agent:<site>:<name>:heartbeat` keys, drops stale entries, diffs against the expected agent roster per site, queries Timescale for incidents-in-last-hour per site, and writes `fleet:snapshot` to Redis (3× interval TTL).
- New events: `RuleCandidate` ([events.py](apps/agents/shared/events.py)) — rule_id, origin/target site, failure_kind, confidence, shadow_until, occurrence_count, sample_device_ids.

### New API routes (Week 9)
- [apps/api/routes/vision.py](apps/api/routes/vision.py) `POST /vision/analyze` — publishes `vision.request` with a `request_id`, awaits the matching `incidents.vision_addendum` (strict request_id filter), 504 on timeout.
- [apps/api/routes/fleet.py](apps/api/routes/fleet.py) `GET /fleet/state` — reads `fleet:snapshot`.
- [apps/api/routes/federation.py](apps/api/routes/federation.py) `GET /federation/candidates/{site_id}` — reads the per-target candidate list.

### Heartbeats (Week 4)
- [apps/agents/shared/base.py](apps/agents/shared/base.py) `BaseAgent` now publishes a heartbeat every 10s to Redis (`agent:<site>:<name>:heartbeat`, TTL 30s).
- [apps/api/routes/agents.py](apps/api/routes/agents.py) `GET /agents/health` reads them via `SCAN`, optionally filtered by site, returns `{agent, site_id, last_seen_ts, stale_seconds, pid}` per agent.

### Seed data (Weeks 5 + 6)
- [scripts/seed_graph.py](scripts/seed_graph.py) — refactored into pure cypher-plan builders + runner. Now writes:
  - `Site`, `Hall`, `Rack`, `Device` nodes
  - `(Hall)-[:LOCATED_IN]->(Site)`, `(Rack)-[:LOCATED_IN]->(Hall)`, `(Device)-[:MOUNTED_IN]->(Rack)`
  - **`(Server)-[:POWERED_BY]->(PDU)`** — from `pdu.powered_device_ids`
  - **`(Server)-[:DEPENDS_ON]->(Switch)`** — every server depends on its ToR
  - **`(GPU)-[:DEPENDS_ON]->(Server)`** — from `gpu.parent_server_id`
  - **`(Rack)-[:COOLED_BY]->(CRACUnit)`** — hall CRAC cools every rack
- [scripts/_incidents_corpus.py](scripts/_incidents_corpus.py) — 18 curated `PastIncident` records for Forensic few-shot retrieval.
- [scripts/seed_incidents.py](scripts/seed_incidents.py) — upserts into ChromaDB `dcops_incidents`.
- [scripts/_runbooks_corpus.py](scripts/_runbooks_corpus.py) — 18 curated `Runbook` exemplars (NL question → SQL template) across thermal/power/GPU/storage/network/fleet/cooling.
- [scripts/seed_runbooks.py](scripts/seed_runbooks.py) — upserts into ChromaDB `dcops_runbooks`.
- `make seed` chains: `seed_graph.py` → `seed_telemetry_sample.py` → `seed_incidents.py` → `seed_runbooks.py`.

### Forensic data-grounding goes live (Week 5)
With both seeds run, the Forensic agent's pre-wired pipeline now operates against real data:
- `kg.dependency_subgraph(device_id, hops=2)` returns the actual blast-radius neighbors thanks to the new POWERED_BY / DEPENDS_ON / COOLED_BY edges.
- `kg.validate_device_ids(...)` catches LLM hallucinations against the seeded inventory.
- `few_shot.retrieve(symptoms)` pulls similar past incidents with `{root_cause, resolution}` metadata that go straight into the prompt.
- `cache.get/put` survives across restarts because Chroma is persistent.

### Operator goes fully live (Week 6)
- [apps/agents/operator/main.py](apps/agents/operator/main.py) `_retrieve_runbooks()` — Chroma top-20 → cross-encoder rerank → top-5 runbook exemplars are now injected as few-shot patterns in the LLM prompt.
- Polished Plotly chart spec recognizes three shapes:
  - `(time, value_num)` → single line
  - `(time, <category>, value_num)` → multi-series line (one per category)
  - `(<category>, value_num)` → bar chart
  - Axis labels + title (the user's question, truncated) populated automatically.
- `QueryResult` now carries `sources` (top-K runbook ids + scores) and the raw rows in `metadata`.
- [apps/api/routes/query.py](apps/api/routes/query.py) `POST /query` — generates a request_id, subscribes to `query.result`, publishes to `query.<request_id>`, awaits the matching `QueryResult` with a configurable timeout (`OPERATOR_QUERY_TIMEOUT_S`, default 30s). 504 on timeout, 503 when the bus is down. The route uses a ready-event handshake so the subscription is live before the publish (avoids the race where Operator answers before the API is listening).

### Event bus
- [apps/agents/shared/event_bus.py](apps/agents/shared/event_bus.py) — pub/sub + Redis Streams (`publish_stream` for `audit.events` and other durable topics).

### API
- FastAPI at [apps/api/main.py](apps/api/main.py); `/health` works. Other routes return placeholder data.

### Benchmark harness (Week 11)
- [benchmarks/generate.py](benchmarks/generate.py) — `generate(target=200, seed=42)` returns a deterministic list of `Scenario`s built from 11 `_Variant` rows × 3 sites × 4 device picks + curated YAML scenarios + multi-signal cascades + federated cross-site shapes, padded with seeded random re-rolls. `categorise(name)` buckets each into gpu/psu/thermal/cooling/network/storage/multi/federated.
- [benchmarks/runner.py](benchmarks/runner.py) — `run_one(scenario, bus)` sets up subscribers BEFORE publishing `simulator.inject`, collects `predictions.failure` / `incidents.report` / `recommendations.*` / `federation.rule_candidate.*` events for `expected_detection.within_seconds + grace_s` (default 120s), scores detection latency + fuzzy RCA match + action recall + propagation flag. `run_batch(..., workers=N)` bounds concurrency for live runs.
- [benchmarks/report.py](benchmarks/report.py) — `render(results)` produces a single-file HTML report. Headline metrics map to README targets (>0.80 precision, >0.70 RCA top-1, <60s MTTD, <120s p95-MTTD, <$0.02 cost/incident, >0.70 action recall, >0.80 federation propagation). Per-category breakdown + LLM cost analysis + per-scenario detail with site/category pill.
- `make bench` runs the full sweep + report.

### Dashboard (Week 10)
- [apps/dashboard/lib/api.ts](apps/dashboard/lib/api.ts) — typed API client + SWR hooks for every endpoint (`useFleetState`, `useIncidents`, `useIncident`, `useTwinState`, `useTelemetryRange`, `useRecommendations`, `useCandidates`, `useAgentHealth`, `postQuery`). 5-second live refresh, dedupe, graceful 503/504 surfacing.
- [apps/dashboard/components/](apps/dashboard/components/) — `StatusBadge`, `MetricCard`, `IncidentRow`, `ThermalHeatmap`, `PlotlyChart` (Plotly dynamic-imported to avoid SSR `window` access).
- [apps/dashboard/app/page.tsx](apps/dashboard/app/page.tsx) — Fleet overview with 4 headline metrics, per-site cards (link to drill-down), and the last 5 recommendations.
- [apps/dashboard/app/incidents/page.tsx](apps/dashboard/app/incidents/page.tsx) — Two-pane: list (with All / per-site filter chips) + a detail panel that fetches `/incidents/{id}` and renders ranked hypotheses, affected devices, LLM cost/model, audit-lineage endpoint.
- [apps/dashboard/app/sites/[id]/page.tsx](apps/dashboard/app/sites/[id]/page.tsx) — thermal heatmap (per-hall grid of rack cells colored by inlet temp), recent-incidents column, and two Plotly line charts (inlet °C and power W over the last hour).
- [apps/dashboard/app/twin/page.tsx](apps/dashboard/app/twin/page.tsx) — Three.js 3D twin: racks laid out in their actual Neo4j position (`[row, col]`) per hall, colored by inlet temp with the same ramp as the heatmap, hover tooltip shows rack id + inlet/outlet/device count, OrbitControls + dark grid + legend chips.
- [apps/dashboard/app/query/page.tsx](apps/dashboard/app/query/page.tsx) — NL query interface with site filter + example chips, posts to `/query`, renders the returned `chart_spec` via Plotly, falls back to a rows table when no chart spec, lists the runbook sources that informed the answer.

### Tests
- **267 unit tests pass — no exclusions, no warnings.**
- Week 9 added: cross-site correlator (5 — confidence floor, threshold, cooldown, candidate marshaling, end-to-end with fake bus), fleet-view aggregator (4), fleet + federation routes (6), Vision route (4 — 503/504/round-trip/strict request_id match).
- Also fixed the lingering `pubsub.close() → aclose()` DeprecationWarning in [event_bus.py](apps/agents/shared/event_bus.py).

### Quality gates
- [pyproject.toml](pyproject.toml) configures ruff, black, mypy strict, pytest with coverage.
- [.pre-commit-config.yaml](.pre-commit-config.yaml) blocks committing `.env`.
- [.github/workflows/ci.yml](.github/workflows/ci.yml) runs lint + unit tests + dashboard build + docker-compose config validation.

---

## What's stubbed

| File | What it does today | When real |
|---|---|---|
| `data/models/sentinel.xgb` | Training pipeline ready; needs Backblaze download + training run | `bash scripts/download_backblaze.sh && python scripts/train_sentinel.py` |
| [apps/api/grpc/](apps/api/grpc/) | proto only; federation rides on Redis pub/sub today | Future hardening |
| WebSocket push for incidents | dashboard polls every 5s instead | Future hardening |
| Live `make bench` reference HTML in `case_study/` | not committed; runs on demand against a live stack | Week 12 / out-of-band |
| Durable `actions.*` topics (Redis Streams + consumer groups) | currently pub/sub | Future hardening |

---

## How to verify

```bash
cp .env.example .env
make install                                  # uv sync + npm install + pre-commit install
make test                                     # unit tests (no docker required)
docker compose --profile dev --profile mocks up -d
docker compose run --rm ollama-init           # warm the OSS models
```

Then:

- `redis-cli -h localhost MONITOR` shows `telemetry.*` traffic from BOTH the simulator and the four normalizers within ~10s.
- `curl http://localhost:8090/health` returns the mocks service status.
- `curl http://localhost:8090/redfish/v1/Systems` returns a Redfish System collection.
- `curl http://localhost:8090/metrics/dcgm` returns Prometheus-format DCGM exposition.
- After ~5 min: `psql -h localhost -U dcops -d dcops -c "SELECT count(*) FROM telemetry;"` should return well into the hundreds of thousands.
- `docker logs dcops-forensic-frankfurt` shows the agent ready with its quality stack flags.

---

## Next up — release v1.0.0 (off-keyboard)

The code is complete; the v1.0.0 tag waits on a live machine. The full
checklist lives at [case_study/release_checklist.md](case_study/release_checklist.md).
Short version:

1. **Optional — train Sentinel:** `bash scripts/download_backblaze.sh && python scripts/train_sentinel.py && docker compose restart sentinel-frankfurt`
2. **Run the benchmark sweep:** `make demo && docker compose run --rm ollama-init && make seed && make bench` → produces `case_study/benchmark_report.html`. Copy the verdicts into [case_study/DRAFT.md § Measured outcomes](case_study/DRAFT.md) and [case_study/metrics_template.md](case_study/metrics_template.md).
3. **Visual review the dashboard:** `cd apps/dashboard && npm install && npm run dev`. Walk the 5 routes. Screenshot for the README under `case_study/screenshots/`.
4. **Record the demo:** Follow [case_study/demo_script.md](case_study/demo_script.md). 10 minutes.
5. **Tag:** `make test && make lint && make typecheck && git tag -a v1.0.0`.

### Production-readiness shortlist (post-v1.0.0)

- Durable `actions.*` topics (Redis Streams + consumer groups so a Rollback restart resumes pending verifications).
- Real gRPC federation streams (heartbeats, incident reports, policy broadcasts).
- WebSocket push for incidents (dashboard subscribes instead of polling).
- Real vendor action libraries (Dell Redfish, NVIDIA DCGM).
- Multi-tenant RBAC + per-tenant LLM cost isolation.
- Kubernetes deployment manifests.

### Out-of-band (still pending from Week 4)
```
bash scripts/download_backblaze.sh
python scripts/train_sentinel.py
docker compose restart sentinel-frankfurt
```

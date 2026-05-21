# DCOps Copilot — 12-Week Build Roadmap

> Solo build. 16GB laptop. Twelve weeks. The plan is divided into four phases. Each week ships a vertical slice — not a finished layer — and ends with a concrete demo state. If a week slips, the next week's deliverable is cut, never deferred indefinitely.
>
> **How to read this:** scan the "demo state at end of week" lines first. That's what the user (or recruiter, or hiring manager) would see if you opened a laptop on Friday afternoon.
>
> Conventional commits with weekly tags (`feat(week-3): physics thermal model`) make the git log a roadmap too. Search the codebase for `TODO(week-N):` to find every stub that ships in week N.

---

## Status legend

- ✅ shipped
- 🟡 in progress
- ⬜ stubbed (scaffold present, real logic deferred)

---

## Phase 1 — Foundation (Weeks 1–3)

> Goal: a runnable platform skeleton. Telemetry flows. Agents subscribe. Dashboard renders. Nothing yet predicts or reasons — that's Phase 2.

### Week 1 — Repo scaffold + data plane

**Deliverables**
- ⬜ Complete repo structure, README/ARCHITECTURE/ROADMAP/CONTRIBUTING written.
- ⬜ `docker-compose.yml` with `data`, `dev`, `demo` profiles and explicit memory caps.
- ⬜ TimescaleDB, Neo4j, ChromaDB, Redis, MinIO running with healthchecks.
- ⬜ `make seed` populates Neo4j with 3 sites × 20 racks × ~600 devices.
- ⬜ `make test` runs and passes (skeleton tests).
- ⬜ Pre-commit hooks installed.

**Success criteria**
- `docker compose --profile data up` boots all 5 stores in < 60s and stays under 3 GB RAM combined.
- `python scripts/seed_graph.py` runs to completion; `MATCH (s:Site) RETURN count(s)` returns 3.

**Demo state**
- A talk-through of the architecture, with all infrastructure running locally. No agents doing real work yet.

---

### Week 2 — Ingestion + simulator + event bus

**Deliverables**
- ⬜ `apps/ingestion/schema.py` — `TelemetryEvent` Pydantic model + canonical metric catalog.
- ⬜ `apps/agents/shared/event_bus.py` — Redis pub/sub wrapper with typed publish/subscribe.
- ⬜ `apps/simulator/` — generates ~5 kHz of `TelemetryEvent`s across 3 sites with realistic diurnal patterns.
- ⬜ `apps/ingestion/normalizers/` — stub normalizers for Redfish, DCGM, IPMI, SNMP (they accept fake payloads in the same shape the simulator produces).
- ⬜ TimescaleDB hypertables created; ingestion service writes events.
- ⬜ Each agent's `main.py` skeleton in place, subscribed to its topic, logging "saw event X".

**Success criteria**
- `docker compose --profile dev up` shows telemetry flowing in `redis-cli MONITOR`.
- A SQL query against TimescaleDB returns > 100K rows after 5 minutes of runtime.
- Each agent's container logs show at least one received event per second.

**Demo state**
- Open `docker logs sentinel`, see telemetry events streaming. Open `redis-cli`, see `telemetry.*` topics busy. No predictions yet — Sentinel just observes.

---

### Week 3 — Physics engine + failure injection + API skeleton

**Deliverables**
- ⬜ `apps/physics/thermal.py` — simple inlet/outlet temp model based on device power draw and CRAC capacity.
- ⬜ `apps/physics/power.py` — PDU → server power propagation; PSU efficiency curves.
- ⬜ `apps/physics/failure_injector.py` — programmatic API to flip a device into a failure mode.
- ⬜ `scripts/inject_failure.py` — CLI wrapping the injector.
- ⬜ `apps/api/main.py` — FastAPI with `/health`, `/telemetry/recent`, `/incidents`, `/twin/state` endpoints (mostly returning placeholder data).
- ⬜ Audit log substrate: `audit.events` Redis stream + MinIO writer.

**Success criteria**
- `make inject SCENARIO=gpu_ecc_failure SITE=frankfurt` runs and produces a visible spike in telemetry on that site's GPU.
- `curl localhost:8080/health` returns OK.
- `curl localhost:8080/telemetry/recent?site=frankfurt&limit=10` returns the latest 10 events.

**Demo state**
- Inject a failure, watch the simulator's downstream telemetry change in real time. Show the API returning the affected device's recent readings. **Phase 1 ends with a complete, observable, controllable simulated data center.**

---

## Phase 2 — Agents (Weeks 4–7)

> Goal: each agent does its real job. The 5 specialized agents go from "logs that they saw the event" to "produces useful structured output."

### Week 4 — Sentinel (predictive failure)

**Deliverables**
- ⬜ Download + preprocess Backblaze SMART dataset (`scripts/download_backblaze.sh`).
- ⬜ XGBoost classifier trained on Backblaze + synthetic GPU XID data.
- ⬜ Rule layer for known-deterministic signals (XID codes, ECC thresholds).
- ⬜ Sentinel publishes `predictions.failure` events with `{device_id, failure_kind, probability, horizon_hours, evidence}`.
- ⬜ Sentinel inference cadence is configurable (default 30s); CPU usage observed and tuned for the 16GB laptop.

**Success criteria**
- On a held-out validation slice, precision at 24h horizon > 0.7. (Target 0.8 by Week 12.)
- A scripted injected GPU ECC failure is flagged by Sentinel within 60s.

**Demo state**
- Inject a failure; within 60s, the dashboard's incident timeline (still a stub view) shows a Sentinel prediction with confidence.

---

### Week 5 — Forensic (Auto-RCA)

**Deliverables**
- ⬜ Neo4j Cypher queries: "all devices within 2 hops of X via DEPENDS_ON / POWERED_BY / COOLED_BY".
- ⬜ ChromaDB seeded with synthetic historical incident reports.
- ⬜ Forensic agent main loop:
  1. Subscribe to `predictions.failure`.
  2. Pull 5-min telemetry window from TimescaleDB.
  3. Pull subgraph from Neo4j.
  4. Find top-K similar past incidents from ChromaDB.
  5. Compose a structured RCA prompt; send to Haiku.
  6. Self-rate confidence; if < threshold, re-run on Sonnet.
  7. Publish `incidents.report`.
- ⬜ `apps/agents/shared/llm_router.py` — full implementation with cost tracking, daily budget guard, and audit logging.

**Success criteria**
- For 5 manually-curated injected scenarios, Forensic's top-1 hypothesis matches the actual root cause.
- LLM router logs show Haiku used for ≥ 80% of RCA calls (Sonnet only on escalation).

**Demo state**
- Inject a failure. Within 90s see: Sentinel prediction → Forensic RCA report visible via `curl /incidents/{id}` → audit log shows which model was used and the cost.

---

### Week 6 — Operator (NL query)

**Deliverables**
- ⬜ NL → SQL pipeline targeting TimescaleDB hypertables.
- ⬜ Semantic retrieval against ChromaDB runbook collection.
- ⬜ Operator endpoint: POST `/query { "question": "..." }` → structured response with `{answer_text, sql_executed, chart_spec, sources}`.
- ⬜ Plotly chart spec generation for time-series answers.

**Success criteria**
- 10 test questions ("which racks ran hottest last 24h?", "what's the power draw trend for hall fra-h1?") each return a structured answer with a chart.
- Per-question Haiku cost < $0.01.

**Demo state**
- `curl -X POST /query -d '{"question": "show me the 5 hottest racks at Frankfurt yesterday"}'` returns answer text + a chart spec.

---

### Week 7 — Optimizer + Planner

**Deliverables**
- ⬜ **Optimizer:** OR-Tools bin-packing for workload-to-rack placement. Constraints: thermal headroom (from physics), power budget per PDU, anti-affinity for redundant workloads.
- ⬜ Optimizer subscribes to `incidents.report` (e.g. hot rack) and emits `recommendations.workload_migration`.
- ⬜ **Planner:** Prophet for capacity forecasting on power draw, thermal load, GPU utilization across 30/60/90-day horizons.
- ⬜ Planner runs hourly; publishes `forecasts.<horizon>` events.

**Success criteria**
- Given a synthetic "rack 7 overheating" incident, Optimizer recommends moving a top-3 by-power workload to a cooler rack within 10s solver time.
- Planner generates a 90-day forecast for a site in < 30s.

**Demo state**
- Inject a thermal incident. See Sentinel → Forensic → Optimizer's recommendation logged. Planner's nightly run produces visible forecast curves.

---

## Phase 3 — Federation + Frontend (Weeks 8–10)

> Goal: tie it all together. Cross-site intelligence. Closed-loop execution. A dashboard that makes the platform real.

### Week 8 — Executor + Rollback Monitor + policy gate

**Deliverables**
- ⬜ `apps/control_plane/policy_engine.py` — YAML-defined policies, evaluated on every recommendation.
- ⬜ `apps/agents/executor/` — calls mocked Redfish / DCGM endpoints; records every action.
- ⬜ `apps/agents/rollback/` — watches telemetry window post-action; if KPIs worsen, triggers revert.
- ⬜ Policies: blast radius caps, blackout window enforcement, per-site overrides.

**Success criteria**
- Recommendation → policy approval → Executor call → telemetry watch → either commit or revert, all observed end-to-end in logs.
- A scripted "bad action" scenario (action that worsens thermals) triggers an automatic rollback within 5 minutes.

**Demo state**
- Closed-loop demo: inject a failure, watch the whole pipeline fire, including a rollback case.

---

### Week 9 — Vision agent + cross-site correlation

**Deliverables**
- ⬜ `apps/agents/vision/` — accepts image + context, sends to Claude Sonnet vision, returns structured `IncidentVisionAddendum`.
- ⬜ `apps/control_plane/cross_site_correlator.py` — high-confidence rule learned at site A is pushed as candidate to B and C; sites run it in shadow for 48h.
- ⬜ Federation gRPC streams operational; sites and control plane exchange heartbeats and incident reports.

**Success criteria**
- Submit a rack-photo + incident context; Vision returns a structured analysis with confidence.
- A simulated cross-site pattern (e.g. CRAC failure shape at Frankfurt) is detected as a candidate rule at Singapore + Mumbai within 1h.

**Demo state**
- "We learned this failure pattern at one site; here's the alert it pre-empted at another."

---

### Week 10 — Dashboard + Three.js digital twin

**Deliverables**
- ⬜ Next.js 14 dashboard with all five routes implemented:
  - `/` fleet overview (3-site map, headline metrics)
  - `/sites/[id]` per-site drill-down with thermal heatmap
  - `/incidents` timeline + RCA viewer + audit explainability tab
  - `/twin` Three.js 3D twin (rotates on incident; rack glows by temperature)
  - `/query` NL query interface to Operator
- ⬜ WebSocket subscription to incident events for live updates.

**Success criteria**
- `cd apps/dashboard && npm run dev` starts on port 3000.
- All 5 routes render with real data from the live stack.
- Three.js twin updates in real time as failures are injected.

**Demo state**
- Phase 3 ends with the demo a stranger could understand: open the dashboard, inject a failure, narrate what happens.

---

## Phase 4 — Trust, Benchmarks, Polish (Weeks 11–12)

> Goal: prove it works. Measure it. Write it up.

### Week 11 — Benchmark harness + 200 scenarios

**Deliverables**
- ⬜ `benchmarks/scenarios/` — 200 scripted incident scenarios across GPU, PSU, CRAC, thermal, switch, federated categories.
- ⬜ `benchmarks/runner.py` — runs every scenario against the live stack, captures outcomes.
- ⬜ `benchmarks/report.py` — generates HTML benchmark report with the headline metrics table from README.md.
- ⬜ Replay mode: scenarios can be re-run from saved state for regression testing.

**Success criteria**
- `make bench` completes the full 200-scenario sweep in < 30 minutes.
- A benchmark report HTML is produced and committed under `case_study/`.

**Demo state**
- Open `case_study/benchmark_report.html`, point to the precision/recall/MTTD/MTTR numbers.

---

### Week 12 — Case study + demo polish + recording

**Deliverables**
- ⬜ `case_study/DRAFT.md` finalized: Executive Summary, Problem Statement, Architecture, Capabilities, Deployment Story, Measured Outcomes (filled with real numbers), Cost Analysis (LLM spend breakdown by agent), Lessons Learned, Roadmap.
- ⬜ `case_study/demo_script.md` — 10-minute polished script.
- ⬜ Demo recording (video, ~10 min).
- ⬜ README screenshots refreshed.
- ⬜ Repo tagged `v1.0.0`.

**Success criteria**
- Case study reads as a credible engineering writeup, not a marketing doc.
- Demo recording runs end-to-end without manual intervention.
- README quickstart works on a fresh clone.

**Demo state**
- Ship the link.

---

## Cuts list (if a week slips)

Phase 1 is mandatory. From there, ordered by what to cut first if time runs out:

1. **Vision agent** — Week 9; cosmetic in a benchmark sense.
2. **Cross-site correlation** — Week 9; the federation story still works without auto-propagation.
3. **Three.js twin** — Week 10; the dashboard is functional without 3D.
4. **Planner** — Week 7; capacity forecasting is the least-time-sensitive agent.

Phase 4 is never cut — if you don't measure it and write it up, it doesn't count.

---

## Standing tasks (every week)

- Update `case_study/DRAFT.md` with what shipped this week + one lesson learned.
- Commit a short retro to `case_study/retros/week_N.md` (private notes; gitignored if needed).
- Re-run `make test` before pushing to `main`.
- Verify `make demo` still boots on a clean clone (catches bit-rot early).

---

## Out of scope for v1.0

These would be the obvious Week 13+ items if the project continues:

- Real hardware integration (drop the simulator on a single physical rack).
- Kubernetes deployment manifests.
- Multi-operator RBAC.
- Cross-region state-store replication.
- Per-tenant LLM cost isolation.
- A real action library (vendor-specific Redfish / DCGM calls, not mocks).

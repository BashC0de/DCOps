# DCOps Copilot — Case Study (DRAFT)

> Living document. Final form is the v1.0.0 deliverable.
>
> Last updated: 2026-05-23 — end of Week 11 (Phase 4 in flight)

---

## Executive summary

DCOps Copilot is an autonomous multi-site data-center operations platform built by a solo engineer in 12 weeks on a 16 GB laptop. Eight specialized agents collaborate over a unified telemetry stream to predict failures, reason about root cause, optimize thermal and capacity placement, plan forward capacity, run NL queries, analyze multimodal incident imagery, execute closed-loop remediation under explicit policy guardrails, and verify outcomes against KPI regressions — with a full audit trail and a 3D digital twin. A central control plane federates intelligence across three simulated sites (Frankfurt, Singapore, Mumbai): a failure pattern observed at one site is propagated as a candidate rule to the others.

The full stack runs on local OSS by default — **no paid LLM API required**. The LLM router shipped with a pluggable backend; Ollama with `llama3.2:3b` / `qwen2.5-coder:3b` / `qwen2.5:7b` / `deepseek-r1:8b` / `qwen2-vl:7b` is the default. An Anthropic backend (Claude Haiku + Sonnet) is an optional extra for users with an API key. Output quality is recovered against the smaller OSS models via a deliberate quality layer: schema-constrained decoding with retries, KG-grounded device-id validation, cross-encoder rerank over runbook retrieval, few-shot exemplar retrieval over past incidents, verifier/critic loops, semantic response caching, and confidence-based tier escalation.

The platform is evaluated against 200 scripted incident scenarios via a deterministic generator; every headline metric (precision, RCA top-1, MTTD, p95-MTTD, action recall, LLM cost per incident, federation propagation) maps to a specific verdict in the auto-generated `case_study/benchmark_report.html`.

This document is the technical writeup. It is intentionally honest about what was built, what was cut, and what would be done differently.

---

## Problem statement

Modern data-center operations teams face three structural problems:

1. **Telemetry overload.** Dell iDRAC, NVIDIA DCGM, IPMI, SNMP, environmental sensors — every component speaks its own dialect. The team writes the same correlation logic five times.
2. **Tribal RCA.** Senior engineers carry years of root-cause heuristics in their heads. When they leave or are on vacation, MTTR doubles.
3. **No closed loop.** Detection alerts a human; a human reads a runbook; a human types a command. The same loop ran a hundred times the same way.

The hypothesis behind DCOps Copilot: a deterministic ML core (XGBoost + rules layer, Prophet forecasts, OR-Tools placement solver) plus an LLM layer for explanation and unstructured reasoning, gated by an explicit policy engine and an explainable audit trail, can collapse all three problems into one platform — at single-site and multi-site federation scale.

The build constraint — solo engineer, 12 weeks, 16 GB laptop, free OSS by default — is part of the test. If it can't be built and deployed inside that envelope, the result wouldn't transfer to a real ops team's constraints.

---

## Architecture overview

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full design. Briefly:

- **Five layers:** Interface (Next.js + Three.js + Plotly) → Central control plane (fleet view + cross-site correlator + policy engine) → Site stacks (×3) → Data layer (TimescaleDB / Neo4j / ChromaDB / Redis / MinIO) → Telemetry layer (Redfish / DCGM / IPMI / SNMP / env).
- **Eight site-local agents:** Sentinel (predict), Forensic (RCA), Operator (NL query), Optimizer (placement), Planner (forecast), Vision (multimodal), Executor (act), Rollback Monitor (verify).
- **Event bus:** Redis pub/sub between agents inside a site. Redis Streams for durable topics (`audit.events`).
- **Federation:** today via Redis pub/sub coordinated centrally; the gRPC contract in [apps/api/grpc/federation.proto](../apps/api/grpc/federation.proto) is reserved as production hardening.
- **LLM routing:** pluggable `Backend` protocol — Ollama (default, free) or Anthropic (optional). Per-task model selection: classify/summarize → `llama3.2:3b`, NL→SQL → `qwen2.5-coder:3b`, RCA → `qwen2.5:7b`, escalation → `deepseek-r1:8b`, vision → `qwen2-vl:7b`. Confidence-based tier escalation lives in [apps/agents/shared/quality/escalation.py](../apps/agents/shared/quality/escalation.py).

---

## Key capabilities

| Capability | Status | Notes |
|---|---|---|
| Universal `TelemetryEvent` schema | ✅ | Frozen `CanonicalMetric` enum — typos fail at parse time |
| Five normalizers (Redfish/DCGM/IPMI/SNMP/env) | ✅ | Real HTTP polling against a single in-repo FastAPI mocks service |
| Redis event bus with typed pub/sub + Streams | ✅ | Lossy for telemetry, durable streams for `audit.events` |
| TimescaleDB writer + hypertable | ✅ | Batch-flush by count or interval (default 500 events / 2s) |
| Physics engine (thermal + power + failure modes) | ✅ | First-pass models; failure injector covers 11 modes |
| Simulator (3 sites × 20 racks × ~600 devices) | ✅ | Diurnal load patterns + injectable failures |
| Failure-injection CLI | ✅ | `make inject SCENARIO=<name> SITE=<id>` |
| **LLM router (Ollama default, Anthropic optional)** | ✅ | Backend protocol, per-task models, audit-stream publish, daily-budget downgrade |
| **Quality layer** | ✅ | Schema-constrained decoding + retries, KG grounding, cross-encoder rerank, few-shot retrieval, verifier loop, semantic cache, escalation |
| **Sentinel** (rules + ML) | ✅ rules; ⏳ ML weights | 7-rule deterministic layer ships; XGBoost training pipeline ready, awaits a Backblaze run |
| **Forensic** (RCA) | ✅ | Full pipeline: cache → few-shot → schema-constrained call → verifier → KG-ground → publish |
| **Operator** (NL→SQL + retrieval) | ✅ | Chroma top-20 → rerank top-5 → schema-constrained SQL → read-only execute → Plotly |
| **Optimizer** (OR-Tools placement) | ✅ | CP-SAT bin-packing under PDU + thermal + HA-affinity constraints; 10s time limit |
| **Planner** (Prophet forecasts) | ✅ | Hourly tick, 30/60/90-day horizons per (site, metric), linear-fallback when Prophet absent |
| **Vision** (multimodal) | ✅ | OSS vision model (`qwen2-vl:7b`); structured output + verifier + KG ground; `POST /vision/analyze` |
| **Executor** + **Rollback Monitor** | ✅ | Policy-gated action → mock vendor endpoint → pre-action KPI snapshot → delayed verify → auto-revert on regression |
| **Policy engine** | ✅ | 4 rule kinds (`blast_radius` / `blackout_window` / `change_freeze` / `custom`), per-site overrides, precedence (DENIED > NEEDS_HUMAN > APPROVED) |
| **Cross-site correlator** | ✅ | Sliding-window predictions tracking, per-target cooldown, 48h shadow window broadcast |
| **Audit substrate** | ✅ | `audit.events` Redis Stream → MinIO archive, content-addressed by SHA-256 |
| **API** | ✅ | 11 endpoints across `/telemetry`, `/incidents`, `/twin`, `/agents`, `/query`, `/recommendations`, `/forecasts`, `/vision`, `/fleet`, `/federation` |
| **Dashboard** | ✅ | 5 routes live: `/`, `/sites/[id]`, `/incidents`, `/twin`, `/query`. SWR polling at 5s. Three.js twin colored by inlet temperature |
| **Benchmark harness** | ✅ | 200 deterministic scenarios + bus-driven runner + HTML report; replay via state snapshots |
| **Audit-explainability tab in dashboard** | ⏳ partial | Detail panel shows audit-lineage pointer; full audit-stream rendering is a polish item |
| **WebSocket push for incidents** | ⏳ deferred | Dashboard polls every 5s instead |
| **Real gRPC federation streams** | ⏳ deferred | Proto contract committed; today the federation rides on Redis pub/sub |
| **Sentinel ML weights** | ⏳ pending training | `bash scripts/download_backblaze.sh && python scripts/train_sentinel.py` |

---

## Deployment story

The default path uses no paid API:

```bash
cp .env.example .env                           # defaults to LLM_BACKEND=ollama
make install                                   # uv sync + npm install + pre-commit
docker compose --profile dev --profile mocks up -d
docker compose run --rm ollama-init            # pulls the small models (~5 GB)
make seed                                      # Neo4j topology + Chroma corpora
```

To bring up all three sites:

```bash
docker compose --profile demo up -d
```

To exercise the closed loop:

```bash
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
# Within ~60s:
curl localhost:8080/incidents       # Forensic published an IncidentReport
curl localhost:8080/recommendations # Optimizer responded
docker logs dcops-rollback-frankfurt # Rollback Monitor scheduled a KPI check
```

Memory budget: dev profile (1 site) ~5 GB; demo profile (3 sites) ~8 GB combined; Ollama caps at 6 GB with one 7B model resident. Six compose profiles let you scope what's running. The [docker-compose.yml](../docker-compose.yml) memory limits are intentional and load-bearing.

### Optional: paid LLM backend

If you have an Anthropic API key and want maximum quality on hard incidents:

```bash
uv sync --extra anthropic
# In .env:
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=...
```

The router's daily-budget guard (`LLM_DAILY_BUDGET_USD`) trips automatic downgrade to the fast tier when the day's spend exceeds the cap, and emits a `budget.exceeded` event.

---

## Measured outcomes

> Numbers below come from a `make bench` run against the live stack.
> Run `make bench` to produce `case_study/benchmark_report.html` and copy the
> headline table here.

| Metric | Target | Measured |
|---|---|---|
| Predictive precision @ 24h | > 0.80 | __ |
| RCA top-1 accuracy | > 0.70 | __ |
| Mean time to detect (s) | < 60 | __ |
| p95 time to detect (s) | < 120 | __ |
| LLM cost per incident (USD) | < $0.02 | __ |
| Action recommendation recall | > 0.70 | __ |
| Federation propagation rate | > 0.80 | __ |

The benchmark harness is deterministic given the seed (default 42); the same `make bench` run should reproduce within sampling noise on the same machine.

---

## Cost analysis

**Default OSS path: $0 per incident.** Local inference via Ollama has no per-call billing. The router still tracks tokens and latency per call, written to `audit.events` for audit completeness — `usd_cost` is simply 0.0 for the Ollama backend.

**Optional Anthropic path:** when `LLM_BACKEND=anthropic` is set, the router computes USD per call from token counts × Anthropic pricing. The breakdown is direct, not estimated:

- **Forensic** — largest consumer. Schema-constrained Haiku for the primary RCA; Sonnet escalation when self-rated confidence < `FORENSIC_ESCALATION_THRESHOLD` (default 0.65). Per the verifier pass + KG-ground retry, expect 1–3 Haiku calls per incident plus the occasional Sonnet escalation.
- **Operator** — Haiku for NL→SQL. One call per query plus a possible revise when KG grounding flags a non-canonical metric.
- **Vision** — Sonnet (vision) only. Rare; gated by both daily budget and a soft retry through the verifier.
- **Sentinel** — no LLM use on the hot path; rule layer + XGBoost only.
- **Optimizer / Planner / Executor / Rollback** — zero LLM use. Pure OR-Tools / Prophet / HTTP / SQL.

Cost-per-incident with the Anthropic backend, based on observed token counts in unit-tested prompts and Anthropic's published Haiku/Sonnet pricing, should sit comfortably under the $0.02 target — the benchmark report fills in the actual number.

---

## Engineering disciplines that paid off

- **Frozen schemas at the boundary.** `TelemetryEvent`, `CanonicalMetric`, every Pydantic event class — `extra="forbid"` everywhere. Typos failed at parse time, not at 2 AM.
- **Graceful degradation as a design rule.** Every shared client (KG / TS / Vector / Blob) constructs successfully without its backing service. Methods return safe defaults when disconnected. An agent that loses Neo4j keeps operating in a degraded mode.
- **Quality layer as separable modules.** `structured`, `verifier`, `kg_grounding`, `semantic_cache`, `few_shot`, `reranker`, `escalation` — each opt-in per call. Made it possible to ship a working agent with the LLM stack and add quality layers without touching the agent.
- **Bus contract over agent imports.** Agents never import each other. The event bus + Redis Streams substrate is the only coupling. Made the closed-loop work fall out cleanly.
- **Audit content-addressed by hash.** Re-publishing the same `CallRecord` overwrites with identical content. Idempotent. No duplicate detection logic anywhere.
- **One in-repo mocks service.** Instead of chasing four vendor-specific Docker images for Redfish/DCGM/IPMI/SNMP/env, a single FastAPI service mimics all four shapes deterministically. Saved days of yak-shaving.

## What was cut and why

- **Real gRPC federation streams.** The proto is committed. Today's federation rides on Redis pub/sub coordinated centrally — same data shapes, same data flow, no cert pinning + retry-with-backoff + consumer-group replay. Production hardening; demo doesn't need it.
- **WebSocket push for incidents.** Dashboard polls SWR every 5s, which feels live. WS adds an API surface (`/ws`) + backpressure handling not justified under deadline.
- **Sentinel ML weights actually trained.** The training pipeline (`scripts/train_sentinel.py`) is in place and tested; running it needs the Backblaze SMART dataset (gigabytes) downloaded + 10–30 minutes of CPU. Ships as a one-command opt-in.
- **Real action library.** The Executor calls in-repo mock endpoints (`/actions/migrate_workload`, `/actions/fan_speed_adjust`, `/actions/revert`). Real vendor calls (Dell Redfish API, NVIDIA DCGM RPCs) are out of scope.
- **Multi-tenant RBAC + per-tenant LLM cost isolation.** Single-operator demo. RBAC adds API surface and storage we didn't need.
- **Kubernetes manifests.** Docker Compose only. K8s would be a straightforward translation if the demo justified it.
- **Cross-region replicated state stores.** Each site has its own Timescale / Neo4j / Chroma. Cross-site queries go through the control plane.

---

## Lessons learned

- **Writing the architecture doc *first* paid off four weeks later.** The LLM-router boundary, the audit-substrate contract, and the policy-engine decision shape were nailed down in Week 1 prose before any agent code touched them. Half the integration work in Weeks 4–8 became "make the code match the doc."
- **Free-OSS LLM by default was the right call.** The Ollama swap took two days; the quality layers that compensate for smaller models took longer to design but pay back forever. A platform that needs a paid API key to demo is one a stranger won't actually try.
- **Schema-constrained decoding > tweaking prompts.** Once the structured-output wrapper went in (Pydantic schema → Ollama `format` field → validation + retry), an entire category of "the model returned prose, can't parse it" failures disappeared. More leverage than any prompt-engineering iteration.
- **Tests against a fake bus were cheap and load-bearing.** Every agent's pipeline test runs without docker. The "ScriptedBus" pattern (capture publishes, replay scripted events) let the runner unit-tests cover the full scoring path without Redis up.
- **Mocks > vendor images.** Spent ~2h building [apps/mocks/](../apps/mocks/) to emulate Redfish + DCGM + IPMI + SNMP + env all in one FastAPI service. The alternative — four separate vendor-specific containers each with their own quirks — would have eaten a week.
- **Heartbeats are cheaper than service discovery.** Every `BaseAgent` writes a TTL'd Redis key every 10s. Dead agents drop off automatically. `GET /agents/health` is a 5-line SCAN. No registry server, no leader election, no consensus.
- **The biggest deferred risk: the dashboard isn't programmatically verified.** Backend has 286 tests; the dashboard ships as TypeScript + React + Three.js with no automated UI testing. The Three.js twin needs human eyes to verify it actually looks right.
- **The biggest cut I'd reconsider: real Redis Streams for `actions.*`.** A restart of the Rollback Monitor today loses the in-memory schedule. For a production deploy this would be the first thing to harden.

---

## Verification

| Surface | How |
|---|---|
| **Test suite** | `make test` → 286 unit tests, no warnings |
| **Type check** | `make typecheck` (mypy strict on `apps/`) |
| **Lint** | `make lint` (ruff + mypy + eslint) |
| **Docker compose validity** | `docker compose --profile demo config --quiet` |
| **Live closed loop** | `make demo && make seed && make inject SCENARIO=gpu_ecc_failure SITE=frankfurt` |
| **Benchmark sweep** | `make bench` — completes < 30 min on a 16 GB laptop |
| **Dashboard** | `cd apps/dashboard && npm install && npm run dev` → 5 routes against the running stack |

---

## Roadmap beyond v1.0.0

See [ROADMAP.md](../ROADMAP.md). Production-readiness shortlist:

- **Durable `actions.*` topics.** Switch from pub/sub to Redis Streams with consumer groups so a Rollback Monitor restart resumes pending verifications.
- **Real gRPC federation.** Implement the proto streams. Heartbeats every 5s, incident reports in real time, policy broadcasts. Sites continue with last-known policy on partition.
- **WebSocket push for incidents.** New API surface; dashboard subscribes instead of polling.
- **Real hardware integration.** Vendor-specific Redfish + DCGM action libraries against a small physical rack.
- **Multi-tenant RBAC + per-tenant LLM cost isolation.**
- **Kubernetes deployment manifests.**
- **Cross-region replicated state stores.**

---

## Acknowledgements

The platform builds on a stack of OSS components — TimescaleDB, Neo4j Community Edition, ChromaDB, Redis, MinIO, FastAPI, Pydantic, OR-Tools, Prophet, XGBoost, sentence-transformers, Ollama, Next.js, Three.js, react-plotly.js — none of which were modified. Every dependency choice is in `pyproject.toml` and `apps/dashboard/package.json`. Apache 2.0 throughout.

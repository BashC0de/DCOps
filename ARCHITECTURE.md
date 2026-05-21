# DCOps Copilot — Architecture

> A deep-dive into the system design. This document is the technical contract: when a behavior here disagrees with code, the code is wrong (or this doc is stale — file an issue either way).

## Table of contents

1. [Design principles](#design-principles)
2. [The five-layer architecture](#the-five-layer-architecture)
3. [Data flow](#data-flow)
4. [The `TelemetryEvent` schema](#the-telemetryevent-schema)
5. [Agent collaboration via the event bus](#agent-collaboration-via-the-event-bus)
6. [Federation model](#federation-model)
7. [Knowledge graph schema](#knowledge-graph-schema)
8. [LLM routing strategy](#llm-routing-strategy)
9. [Explainability and audit](#explainability-and-audit)
10. [Memory budget](#memory-budget)
11. [Failure modes and recovery](#failure-modes-and-recovery)

---

## Design principles

1. **Vertical slices over horizontal layers.** Each weekly milestone ships a thin end-to-end path, not a finished horizontal stratum.
2. **Telemetry is the universal language.** Every source — Redfish, DCGM, IPMI, SNMP, environmental — normalizes to a single `TelemetryEvent` schema before anything else touches it.
3. **Agents collaborate through the bus, not through imports.** Agents are decoupled processes that subscribe to event topics. This makes them independently deployable, testable, and replaceable.
4. **The LLM is a tool, not the brain.** ML models (XGBoost, Prophet, OR-Tools) carry the deterministic load; LLMs explain, escalate, and translate.
5. **Closed-loop with the brakes on.** Every automated action goes through a policy gate and a rollback monitor. The system can act, but it can also stop itself.
6. **Federated by default, autonomous on partition.** A site can run unilaterally if the central plane is unreachable.
7. **Memory caps are load-bearing.** This was built on a 16GB laptop; every cap in `docker-compose.yml` is intentional.

---

## The five-layer architecture

```
┌───────────────────────────────────────────────────────────────────┐
│ Layer 1 — Interface                                               │
│  Next.js dashboard · Three.js twin · NL query · Audit viewer      │
├───────────────────────────────────────────────────────────────────┤
│ Layer 2 — Central Control Plane                                   │
│  Fleet view · Cross-site correlator · Policy engine               │
├───────────────────────────────────────────────────────────────────┤
│ Layer 3 — Site Stacks (×N, federated via gRPC streams)            │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │ Sentinel · Forensic · Operator · Optimizer · Planner    │     │
│  │ Action Executor · Rollback Monitor · Vision Agent       │     │
│  └──────────────────────────────────────────────────────────┘     │
├───────────────────────────────────────────────────────────────────┤
│ Layer 4 — Data                                                    │
│  TimescaleDB (time-series) · Neo4j (KG) · ChromaDB (vectors)      │
│  Redis (event bus + cache) · MinIO (raw archive)                  │
├───────────────────────────────────────────────────────────────────┤
│ Layer 5 — Telemetry                                               │
│  Redfish · DCGM · IPMI · SNMP · Env sensors → Ingestion service   │
└───────────────────────────────────────────────────────────────────┘
```

### Layer 1 — Interface

The Next.js dashboard at `apps/dashboard/` is the single human pane of glass. Five routes:

- `/` — fleet overview across all sites
- `/sites/[id]` — per-site drill-down with thermal heatmap
- `/incidents` — incident timeline + RCA viewer
- `/twin` — Three.js digital twin (rotates to relevant rack on incident)
- `/query` — natural-language query interface (Operator agent)

The dashboard talks to the FastAPI backend over REST + WebSockets. No agent logic runs in the browser.

### Layer 2 — Central Control Plane

Three modules under `apps/control_plane/`:

- **Fleet view** (`fleet_view.py`) — aggregates per-site state into a single materialized fleet snapshot, exposed to the dashboard.
- **Cross-site correlator** (`cross_site_correlator.py`) — when site A's Sentinel flags a pattern with confidence > threshold, the correlator pushes the rule to sites B and C with a "candidate detection" status. This is the federation payoff.
- **Policy engine** (`policy_engine.py`) — a YAML-defined ruleset that gates every Executor action. Blast radius, blackout windows, change-freeze, and per-site policy overrides all live here.

The control plane has no direct ingestion or remediation path. It coordinates; site stacks act.

### Layer 3 — Site Stacks

Each site runs an identical stack. Communication inside a site is through the Redis event bus; communication between site and control plane is via gRPC streams. The eight components in a site stack are:

| Component | Subscribes to | Publishes |
|---|---|---|
| Sentinel | `telemetry.*` | `predictions.failure` |
| Forensic | `predictions.failure`, `alerts.*` | `incidents.report` |
| Operator | direct API call | `query.result` |
| Optimizer | `incidents.report`, `capacity.request` | `recommendations.*` |
| Planner | scheduled (hourly) | `forecasts.*` |
| Vision | direct API call (with image) | `incidents.vision_addendum` |
| Action Executor | `recommendations.*` (with policy approval) | `actions.executed` |
| Rollback Monitor | `actions.executed` | `actions.rolled_back` |

### Layer 4 — Data

| Store | Purpose | Notes |
|---|---|---|
| TimescaleDB | Time-series telemetry | One hypertable per metric family; 7-day raw retention, 30-day downsampled |
| Neo4j Community | Asset + dependency graph | See [§ Knowledge graph schema](#knowledge-graph-schema) |
| ChromaDB | Incident embeddings + runbook chunks | Two collections: `incidents` and `runbooks` |
| Redis | Event bus + per-agent cache | `maxmemory` enforced; LRU eviction |
| MinIO | Raw log + artifact archive | S3-compatible; lifecycle rules in `infra/` |

### Layer 5 — Telemetry

The ingestion service at `apps/ingestion/` runs per-source normalizers:

- `redfish.py` — Dell iDRAC over HTTPS, polls `/redfish/v1/Systems/*`
- `dcgm.py` — NVIDIA DCGM exporter scrape
- `ipmi.py` — IPMI over LAN, sensor table + SEL
- `snmp.py` — Switch/PDU OIDs
- `env.py` — CRAC unit + environmental sensor feeds

Each normalizer emits `TelemetryEvent` records to the Redis bus topic `telemetry.<source>.<device_type>`.

In dev, the **simulator** at `apps/simulator/` substitutes for real hardware — see [§ Failure modes](#failure-modes-and-recovery).

---

## Data flow

A single incident travels this path:

```
            ┌─────────────────────┐
            │ Telemetry source    │  (real hw OR simulator)
            └──────────┬──────────┘
                       │ raw record
                       ▼
            ┌─────────────────────┐
            │ Ingestion normalizer│
            └──────────┬──────────┘
                       │ TelemetryEvent
                       ▼
   ┌───────────────────┴───────────────────────────┐
   │   Redis bus topic: telemetry.<src>.<type>     │
   └───────────────────┬───────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌──────────────────┐
   │TimescaleDB│   │ Sentinel│    │ Other subscribers│
   │ (persist) │   │ (infer) │    │ (Optimizer, ...) │
   └─────────┘    └────┬────┘    └──────────────────┘
                       │ PredictedFailure event
                       ▼
                  ┌─────────┐
                  │Forensic │  (queries KG + ChromaDB; routes to Haiku)
                  └────┬────┘
                       │ IncidentReport event
                       ▼
                  ┌─────────┐
                  │Optimizer│  (OR-Tools bin-packing; emits Recommendation)
                  └────┬────┘
                       │ Recommendation
                       ▼
                  ┌─────────────────────────┐
                  │ Policy engine (gate)    │
                  └────┬──────────────┬─────┘
                       │ approved     │ denied → human review queue
                       ▼              ▼
                  ┌─────────┐    [escalate to operator]
                  │Executor │  (mocked Redfish/DCGM call)
                  └────┬────┘
                       │ ActionExecuted
                       ▼
                  ┌──────────────────┐
                  │ Rollback Monitor │  (watches telemetry window)
                  └──────────────────┘
```

Every event in this flow is written to the audit log (`audit.events` Redis stream + MinIO archive) with timestamp, agent ID, input summary hash, output summary hash, LLM cost (if applicable), and confidence.

---

## The `TelemetryEvent` schema

The universal payload. Defined in `apps/ingestion/schema.py`. Every component in the system reads and writes this Pydantic model — no exceptions.

```python
class TelemetryEvent(BaseModel):
    timestamp: datetime              # UTC, microsecond precision
    site_id: str                     # e.g. "frankfurt"
    hall_id: str                     # e.g. "fra-h1"
    rack_id: str                     # e.g. "fra-h1-r07"
    device_id: str                   # e.g. "fra-h1-r07-srv03"
    device_type: DeviceType          # enum: SERVER | GPU | SWITCH | PDU | CRAC | SENSOR
    metric: str                      # canonical metric name, e.g. "gpu.ecc.uncorrectable"
    value: float | int | str         # raw value
    unit: str | None                 # e.g. "celsius", "watts", "count"
    severity: Severity               # enum: INFO | WARN | ERROR | CRITICAL
    metadata: dict[str, Any]         # source-specific extras (XID code, sensor ID, etc.)
```

**Canonical metric names** follow a `<component>.<dimension>.<aspect>` pattern:

- `cpu.temp.celsius`
- `gpu.ecc.uncorrectable`
- `gpu.xid.code`
- `power.draw.watts`
- `fan.rpm`
- `psu.efficiency.percent`
- `env.inlet.celsius`
- `env.humidity.percent`

The metric catalog lives in `apps/ingestion/schema.py` as a frozen enum so typos fail at parse time.

---

## Agent collaboration via the event bus

Redis Pub/Sub is the substrate. Topic conventions:

```
telemetry.<source>.<device_type>        # ingestion → all
predictions.failure                      # sentinel → forensic, optimizer
alerts.<severity>                        # any agent → forensic
incidents.report                         # forensic → optimizer, dashboard
recommendations.<kind>                   # optimizer/planner → executor (via policy)
actions.executed                         # executor → rollback, dashboard
actions.rolled_back                      # rollback → forensic, dashboard
query.<request_id>                       # dashboard → operator
forecasts.<horizon>                      # planner → dashboard, optimizer
audit.events                             # ALL → audit sink (Redis stream)
```

The wrapper in `apps/agents/shared/event_bus.py` exposes:

```python
async def publish(topic: str, event: BaseEvent) -> None
async def subscribe(topic_pattern: str) -> AsyncIterator[BaseEvent]
```

Every agent's `main.py` follows this pattern:

```python
async def main():
    bus = EventBus.from_env()
    async for event in bus.subscribe("predictions.failure"):
        result = await handle(event)
        await bus.publish(f"incidents.report", result)
        await audit_log(agent="forensic", event=event, result=result)
```

**Why pub/sub over a queue?** Several agents subscribe to the same topic. A queue (where each message is consumed once) would force fan-out logic into the producer. Pub/sub keeps the producer ignorant of consumers, which is the right coupling.

**Backpressure:** if a subscriber lags, Redis drops messages from its queue. We tolerate this for telemetry (it's high-volume; missing one sample is fine) but not for `actions.*` (durable Redis streams, not pub/sub).

---

## Federation model

Three sites, one central plane. The interaction is **gRPC streams in both directions**:

```
   ┌─────────────────┐                      ┌─────────────────┐
   │  Frankfurt site │  ◄────── gRPC ─────► │  Control Plane  │
   └─────────────────┘                      └─────────────────┘
                                                    ▲
                                                    │
   ┌─────────────────┐                              │
   │  Singapore site │  ◄────── gRPC ───────────────┤
   └─────────────────┘                              │
                                                    │
   ┌─────────────────┐                              │
   │  Mumbai site    │  ◄────── gRPC ───────────────┘
   └─────────────────┘
```

### Site → Control plane

Each site pushes:

- A heartbeat with summarized health every 5s.
- Every `incidents.report` event in real time.
- A nightly bulk dump of new detection rules learned by Sentinel.

### Control plane → Site

- **Detection rule propagation:** a high-confidence Sentinel rule learned at site A is pushed as a "candidate" to B and C. Each receiving site enables it in shadow mode for 48h before active use.
- **Policy updates:** a new YAML policy is broadcast to all sites within 1s.
- **Coordinated remediation:** for blast-radius-wide changes (e.g. CRAC failure at one site triggering load shift to others), the control plane coordinates.

### Autonomy on partition

If gRPC to the control plane is unreachable for > 30s, the site logs a `degraded.federation` alert and continues operating with the last-known policy + ruleset. When the link returns, the site replays any held-back updates and reconciles state. **A site never refuses to remediate just because the control plane is offline** — the policy gate is local-first.

---

## Knowledge graph schema

Neo4j Community Edition holds the asset + dependency graph. The schema is intentionally narrow.

**Node labels:**

```
(:Site {id, region, timezone})
(:Hall {id, site_id, capacity_kw})
(:Rack {id, hall_id, position, capacity_u})
(:Device {id, type, model, vendor, install_date})
(:Workload {id, name, tier, owner})
(:Incident {id, opened_at, closed_at, severity, root_cause})
(:Policy {id, kind, scope})
```

**Relationships:**

```
(Hall)-[:LOCATED_IN]->(Site)
(Rack)-[:LOCATED_IN]->(Hall)
(Device)-[:MOUNTED_IN]->(Rack)
(Device)-[:DEPENDS_ON]->(Device)              // e.g. server -> switch
(Device)-[:POWERED_BY]->(Device)              // server -> PDU
(Device)-[:COOLED_BY]->(Device)               // rack -> CRAC unit
(Workload)-[:RUNS_ON]->(Device)
(Incident)-[:AFFECTED]->(Device)
(Incident)-[:SIMILAR_TO {score}]->(Incident)  // computed nightly
(Policy)-[:APPLIES_TO]->(Site|Hall|Rack|Device)
```

The graph is the Forensic agent's primary reasoning surface. Given a failing device, it queries: "show me everything within 2 hops that could be a cause or a victim" — and feeds that subgraph to the LLM as part of the RCA prompt.

The `SIMILAR_TO` edge is computed by ChromaDB nightly (cosine similarity over incident embeddings) and written back to Neo4j. This is the "we've seen this before" signal.

---

## LLM routing strategy

LLMs are expensive. We treat them as a tiered resource and route by confidence + cost.

```
                ┌──────────────────────────────┐
                │ Agent needs LLM help         │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ llm_router.route(request)    │
                └──────────────┬───────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Routine / classify   Complex      Escalation:
        ┌─────────┐         ┌─────────┐   Haiku conf < 0.65
        │ Haiku   │         │ Haiku   │   ┌─────────┐
        └─────────┘         └────┬────┘   │ Sonnet  │
                                 │        └─────────┘
                            (post-check
                            confidence;
                            escalate if low)
```

**Routing inputs:**

1. **Task class** — declared by the agent (`"classify_severity"`, `"explain_root_cause"`, `"compose_runbook_step"`, etc.). Each class has a default tier in `apps/agents/shared/llm_router.py`.
2. **Confidence floor** — Forensic's RCA explicitly self-rates; if confidence < `FORENSIC_ESCALATION_THRESHOLD` (default 0.65), the router re-runs on Sonnet.
3. **Daily budget** — `LLM_DAILY_BUDGET_USD` per agent. Once breached, the router downgrades all Sonnet calls to Haiku and emits a `budget.exceeded` event.

**Every call is logged with:**

- agent ID
- task class
- chosen model
- input token count
- output token count
- USD cost (computed from token counts and per-model rates)
- whether this was a primary call or an escalation

This data feeds the **cost-per-incident** metric in the benchmark report.

---

## Explainability and audit

Trust requires that every automated decision be explainable and reversible. The audit substrate:

1. **`audit.events` Redis stream** — every agent action appends one record:
   ```json
   {
     "ts": "2026-05-21T14:03:11.234Z",
     "agent": "forensic",
     "event_type": "incident_report",
     "input_hash": "sha256:...",
     "output_hash": "sha256:...",
     "llm_calls": [{"model": "haiku", "tokens_in": 1247, "tokens_out": 312, "usd": 0.0023}],
     "confidence": 0.78,
     "policy_decisions": [],
     "trace_id": "..."
   }
   ```

2. **MinIO archive** — full input/output payloads are written to MinIO keyed by hash. The Redis record carries only hashes; the heavy data is in object storage.

3. **OpenTelemetry traces** — agent-to-agent calls carry a `trace_id` so a full incident can be reconstructed end-to-end.

4. **Audit viewer in the dashboard** — every incident card has an "explain" tab that renders the full chain: which agent fired, what input it saw, what the LLM said, what the policy gate decided, what the executor did, what rollback observed.

**An action with no audit record cannot be taken.** The executor refuses to act on a recommendation that doesn't carry a valid audit lineage.

---

## Memory budget

Target: **full demo stack fits in 8GB combined**, leaving 8GB for the host OS, IDE, and browser on a 16GB laptop.

| Service | Memory cap | Notes |
|---|---|---|
| TimescaleDB | 1024 MB | `shared_buffers=256MB`, `effective_cache_size=512MB` |
| Neo4j | 768 MB | 512 MB heap + 256 MB pagecache |
| ChromaDB | 512 MB | Persistent mode, mmap embeddings |
| Redis | 256 MB | `maxmemory 256mb`, `allkeys-lru` |
| MinIO | 256 MB | Single-node mode |
| Ingestion | 256 MB | Stateless |
| Each agent | 384 MB | Sentinel higher (768 MB) when XGBoost loaded |
| Control plane | 256 MB | |
| FastAPI | 256 MB | |
| Next.js (dev) | 512 MB | Production build is smaller |
| Simulator | 256 MB | |

Sum (dev profile, 1 site): **~5 GB.** Demo profile (3 sites): **~8 GB.** Adjust in `docker-compose.yml`; if you raise a cap, update this table.

---

## Failure modes and recovery

| Failure | Detection | Recovery |
|---|---|---|
| Ingestion source down | Heartbeat missing > 30s | Source marked stale; alerts emitted; cached state used |
| Redis crash | `event_bus` reconnect logic | Exponential backoff; in-flight events lost (acceptable for telemetry; not for `actions.*` which use Redis Streams with consumer groups) |
| TimescaleDB down | Write errors | Buffer to MinIO; replay on recovery (Week 8) |
| Neo4j down | Forensic falls back to flat lookup | Reduced RCA quality, no crash |
| Anthropic API down | LLM router catches exceptions | Returns "explain unavailable, see telemetry" stub; incident still recorded |
| Control plane unreachable | Site logs `degraded.federation` | Site continues with last-known policy/ruleset |
| OOM on a service | Docker restarts | Healthcheck flaps logged; budget table needs revisit |

---

## What's intentionally not here

- **Real hardware integration.** The simulator stands in for production. Production-readiness is out of scope for the 12-week build.
- **Multi-tenant access control.** Single-operator demo; RBAC would be a Week 13+ addition.
- **Kubernetes deployment.** Docker Compose only. K8s manifests would be straightforward to derive but aren't shipped.
- **Cross-region replication of state stores.** Each site has its own TimescaleDB/Neo4j/Chroma. Cross-site queries go through the control plane.

See [ROADMAP.md](ROADMAP.md) for the week-by-week shipping plan.

<div align="center">

# DCOps Copilot

**Autonomous Multi-Site Data Center Operations Platform**

*Five specialized AI agents, federated across simulated sites, closing the loop on data center incidents with policy guardrails and a physically-grounded digital twin.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Next.js 14](https://img.shields.io/badge/next.js-14-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Three.js](https://img.shields.io/badge/three.js-r160-000000.svg)](https://threejs.org/)
[![TimescaleDB](https://img.shields.io/badge/timescaledb-2.17-fdb515.svg)](https://www.timescale.com/)
[![Neo4j](https://img.shields.io/badge/neo4j-5-008cc1.svg)](https://neo4j.com/)
[![Anthropic Claude](https://img.shields.io/badge/anthropic-claude%204.7-d97757.svg)](https://www.anthropic.com/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

[Architecture](ARCHITECTURE.md) · [Roadmap](ROADMAP.md) · [Case Study](case_study/DRAFT.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## Why this exists

Modern data center operations teams drown in telemetry from heterogeneous sources — Dell iDRAC, NVIDIA DCGM, IPMI, SNMP, environmental sensors — and respond with brittle, hand-tuned playbooks. Every incident is investigated from scratch. Every capacity plan is a spreadsheet. Every cross-site correlation lives in a senior engineer's head.

**DCOps Copilot is what happens when you give that team an autonomous co-pilot.** Five specialized agents ingest the firehose, reason over it, and act — under explicit policy guardrails, with full audit trails, and an explainable confidence model. A physically-grounded digital twin lets you preview every action before it ships. A central control plane federates intelligence across sites so a failure pattern at Frankfurt informs prevention in Singapore.

This repo is a **complete, runnable reference implementation** — not a slide deck. The full stack boots on a developer laptop. Inject a failure scenario, watch agents collaborate, and read the Three.js twin rotate to the affected rack.

---

## Quickstart

Three commands to a live demo:

```bash
cp .env.example .env                  # add your ANTHROPIC_API_KEY
make seed                             # populate KG + sample telemetry
make demo                             # bring up all 3 sites + dashboard
```

Then open:

- **Dashboard:** http://localhost:3000
- **API docs:** http://localhost:8080/docs
- **Grafana:** http://localhost:3001

To inject a scripted incident:

```bash
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
```

Watch logs stream as Sentinel detects, Forensic explains, Optimizer mitigates, Executor remediates, and Rollback Monitor verifies.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Interface Layer                            │
│   Next.js dashboard · Three.js twin · NL query · Audit viewer  │
├─────────────────────────────────────────────────────────────────┤
│                    Central Control Plane                        │
│       Fleet view · Cross-site correlator · Policy engine       │
├──────────────────┬─────────────────────────┬───────────────────┤
│   Site Stack 1   │   Site Stack 2          │   Site Stack 3    │
│   (Frankfurt)    │   (Singapore)           │   (Mumbai)        │
│  ┌────────────┐  │  ┌────────────┐         │  ┌────────────┐   │
│  │ 5 Agents   │  │  │ 5 Agents   │         │  │ 5 Agents   │   │
│  │ + Executor │  │  │ + Executor │         │  │ + Executor │   │
│  │ + Rollback │  │  │ + Rollback │         │  │ + Rollback │   │
│  │ + Vision   │  │  │ + Vision   │         │  │ + Vision   │   │
│  └────────────┘  │  └────────────┘         │  └────────────┘   │
├──────────────────┴─────────────────────────┴───────────────────┤
│                       Data Layer                                │
│  TimescaleDB · Neo4j KG · ChromaDB · Redis bus · MinIO         │
├─────────────────────────────────────────────────────────────────┤
│                     Telemetry Layer                             │
│  Redfish · DCGM · IPMI · SNMP · Environmental sensors          │
└─────────────────────────────────────────────────────────────────┘
```

Full breakdown — including the `TelemetryEvent` schema, agent collaboration patterns, federation model, and LLM routing strategy — lives in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Capabilities

| Agent | Role | Stack | Status |
|---|---|---|---|
| **Sentinel** | Predictive failure detection | XGBoost on Backblaze SMART + rules for GPU XID codes | ⬜ Week 4 |
| **Forensic** | Auto-RCA with knowledge-graph reasoning | Neo4j + ChromaDB + Claude Haiku/Sonnet | ⬜ Week 5 |
| **Operator** | NL → SQL + semantic retrieval | Claude Haiku + Plotly + TimescaleDB | ⬜ Week 6 |
| **Optimizer** | Thermal + capacity placement | OR-Tools bin-packing + physics engine | ⬜ Week 7 |
| **Planner** | 30/60/90-day capacity forecast | Prophet / ARIMA + Monte Carlo | ⬜ Week 7 |
| **Action Executor** | Closed-loop remediation | Mocked Redfish / DCGM endpoints + policy gate | ⬜ Week 8 |
| **Rollback Monitor** | Post-action verification + revert | Telemetry-window comparison | ⬜ Week 8 |
| **Vision Agent** | Multi-modal incident analysis | Claude Sonnet vision (rack photos / thermal cams) | ⬜ Week 9 |

Status legend: ✅ shipped · 🟡 in progress · ⬜ stubbed (see [ROADMAP.md](ROADMAP.md))

---

## Tech stack

**Backend:** Python 3.11 · FastAPI · gRPC · Pydantic v2 · structlog · OpenTelemetry
**Frontend:** Next.js 14 · TypeScript (strict) · Tailwind · Three.js · Plotly
**Data:** TimescaleDB · Neo4j Community · ChromaDB · Redis · MinIO
**ML / Opt:** XGBoost · Prophet · OR-Tools · sentence-transformers
**LLM:** Anthropic Claude (Haiku + Sonnet with explicit cost routing)
**Ops:** Docker Compose (memory-capped profiles) · Grafana · Pytest

Every database service in `docker-compose.yml` carries an explicit memory limit so the full demo fits on a 16GB laptop. See [ARCHITECTURE.md § Memory budget](ARCHITECTURE.md#memory-budget).

---

## Federation model

Three simulated sites (Frankfurt, Singapore, Mumbai) each run an identical site stack. A central control plane federates them via gRPC streams:

- **Fleet view** — single pane of glass over all sites.
- **Cross-site correlator** — a failure pattern caught at site A pre-seeds detection rules at sites B and C.
- **Policy engine** — every remediation action is checked against a centrally-managed policy (blast radius, blackout windows, change-freeze).

A site can run autonomously if the control plane is unreachable; intelligence sync resumes when the link returns.

---

## Screenshots

> Screenshots land Week 10. Until then, see [`case_study/DRAFT.md`](case_study/DRAFT.md) for the demo script and target visuals.

```
[ Fleet overview · 3 sites · 60 racks · live ]   ← TODO(week-10)
[ Per-site drilldown with thermal heatmap   ]   ← TODO(week-10)
[ Three.js digital twin rotating to failed rack ] ← TODO(week-10)
[ NL query: "Why is rack 7 trending hot?"   ]   ← TODO(week-10)
```

---

## Benchmarks

The platform is evaluated against **200 scripted incident scenarios** spanning GPU ECC failures, PSU degradation, CRAC failures, thermal runaway, switch cascades, and federated cross-site events. See `benchmarks/scenarios/` for the YAML scenario format.

Headline metrics tracked (filled in Week 12):

| Metric | Target | Measured |
|---|---|---|
| Predictive failure precision @ 24h horizon | > 0.80 | TBD |
| RCA top-1 root-cause accuracy | > 0.70 | TBD |
| Mean time to detect (s) | < 60 | TBD |
| Mean time to remediate (s) | < 300 | TBD |
| LLM cost per incident (USD) | < $0.02 | TBD |
| Rollback false-positive rate | < 5% | TBD |

Run `make bench` to reproduce the full benchmark suite locally.

---

## Project layout

```
dcops-copilot/
├── apps/
│   ├── ingestion/       # Telemetry normalizers → event bus
│   ├── agents/          # 5 agents + executor + rollback + vision
│   ├── physics/         # Digital-twin physics engine
│   ├── simulator/       # 3-site synthetic telemetry generator
│   ├── control_plane/   # Federation orchestrator + policy engine
│   ├── api/             # FastAPI backend + gRPC
│   └── dashboard/       # Next.js 14 ops UI
├── benchmarks/          # 200 scenarios + runner + report
├── case_study/          # Living case study + demo script
├── data/                # Seeds + Backblaze SMART (gitignored)
├── infra/               # Per-service Dockerfiles + Grafana boards
├── scripts/             # CLI tools (seed, inject, reset)
└── tests/               # Unit + integration
```

---

## Contributing

This is a solo build, but conventions are public. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for branching, commit format, test discipline, and the definition-of-done checklist.

---

## License

Apache 2.0. See [LICENSE](LICENSE).

---

<div align="center">

Built on a 16GB Intel i5 laptop in 12 weeks. The constraints are the point.

</div>

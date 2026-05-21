# DCOps Copilot — Case Study (DRAFT)

> Living document. Updated weekly with what shipped + what was learned. Final form is the Week 12 deliverable.
>
> Last updated: 2026-05-22 — Week 1 (scaffold complete)

---

## Executive summary

DCOps Copilot is an autonomous multi-site data center operations platform built by a solo engineer in 12 weeks on a 16GB laptop. Five specialized AI agents collaborate over a unified telemetry stream to detect impending failures, reason about root cause, optimize thermal and capacity placement, plan forward capacity, and execute closed-loop remediation — under explicit policy guardrails and full audit. A central control plane federates intelligence across three simulated sites (Frankfurt, Singapore, Mumbai), so a failure pattern at one site is pre-empted at the others. A physically-grounded digital twin lets every action be previewed before it ships. The platform is evaluated against 200 scripted incident scenarios with publicly-reported precision, recall, time-to-detect, time-to-remediate, and LLM-cost-per-incident metrics.

This document is the technical writeup. It is intentionally honest about what was built, what was cut, and what would be done differently with hindsight.

---

## Problem statement

Modern data center operations teams face three structural problems:

1. **Telemetry overload.** Dell iDRAC, NVIDIA DCGM, IPMI, SNMP, environmental sensors — every component speaks its own dialect. The team writes the same correlation logic five times.
2. **Tribal RCA.** Senior engineers carry years of root-cause heuristics in their heads. When they leave or are on vacation, MTTR doubles.
3. **No closed loop.** Detection alerts a human; a human reads a runbook; a human types a command. The same loop ran a hundred times the same way.

The hypothesis behind DCOps Copilot is that a deterministic ML core (XGBoost, Prophet, OR-Tools) plus an LLM layer for explanation and unstructured reasoning, gated by an explicit policy engine and an explainable audit trail, can collapse all three problems into one platform — and that the architecture works at a single-site scale and at a multi-site federation scale.

---

## Architecture overview

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full design. Briefly:

- **Five layers:** Interface (Next.js + Three.js) → Central control plane → Site stacks (×3) → Data layer (TimescaleDB / Neo4j / ChromaDB / Redis / MinIO) → Telemetry layer (Redfish / DCGM / IPMI / SNMP / env).
- **Eight site-local agents:** Sentinel (predict), Forensic (RCA), Operator (NL query), Optimizer (placement), Planner (forecast), Vision (multimodal), Executor (act), Rollback Monitor (verify).
- **Event bus:** Redis pub/sub between agents inside a site; gRPC streams between site and central plane.
- **LLM routing:** Haiku for routine, Sonnet for escalation, with per-agent daily USD budgets enforced at the router.

---

## Key capabilities

| Capability | Status (week 1) | Comments |
|---|---|---|
| Universal `TelemetryEvent` schema | ✅ shipped | Frozen metric catalog; typos fail at parse time. |
| Redis event bus with typed pub/sub | ✅ shipped | Lossy for telemetry, streams (Week 8) for actions. |
| 8 agent process containers | ✅ scaffolded | Each one subscribes + logs; real logic by week. |
| Physics engine (thermal + power) | 🟡 entities + stubs | Numerics in Week 3. |
| Simulator (3 sites × 20 racks) | 🟡 device build + emit | Pattern-modulated load on every tick. |
| Failure injection CLI | ✅ shipped (skeleton) | Five scripted scenarios; 195 more by Week 11. |
| FastAPI backend with 5 route groups | ✅ scaffolded | Health works; rest stubbed. |
| Next.js 14 dashboard, 5 routes | ✅ scaffolded | Renders; data hookup Week 10. |
| Three.js digital twin | 🟡 placeholder | Real geometry Week 10. |
| Federation gRPC contract | ✅ proto written | Server impl Week 9. |
| Policy engine | 🟡 evaluator stub | Default rules loaded; full evaluator Week 8. |
| Benchmark harness | 🟡 runner + report skeletons | 200-scenario sweep Week 11. |
| Audit trail | 🟡 substrate written | Persistence wires up Week 3. |

---

## Deployment story

```
cp .env.example .env                   # add ANTHROPIC_API_KEY
make seed                              # populate Neo4j + initial telemetry
make demo                              # bring up all 3 sites + dashboard
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
```

Memory footprint: full demo profile fits in ~8 GB; dev profile (1 site) in ~5 GB. Six compose profiles let you scope what's running.

---

## Measured outcomes

> All numbers below are placeholders until the Week 11 benchmark run completes.

| Metric | Target | Measured |
|---|---|---|
| Predictive failure precision @ 24h | > 0.80 | TBD |
| RCA top-1 accuracy | > 0.70 | TBD |
| Mean time to detect (s) | < 60 | TBD |
| Mean time to remediate (s) | < 300 | TBD |
| LLM cost per incident (USD) | < $0.02 | TBD |
| Rollback false-positive rate | < 5% | TBD |
| Cross-site rule propagation success @48h | > 60% | TBD |

---

## Cost analysis

> Filled in Week 12 with actual Anthropic invoicing.

Categories tracked:

- **Forensic** (largest LLM consumer; Haiku-first with Sonnet escalation)
- **Operator** (Haiku for NL→SQL; ~20× lower volume than Forensic)
- **Vision** (Sonnet only; rare; gated by daily budget)
- **Sentinel** (LLM only for human-readable explanations; ~$0/incident)
- **Other agents** (no LLM use)

Per the LLM router design, every call is logged with token counts and USD cost, so this breakdown is direct, not estimated.

---

## Lessons learned

> Updated weekly. Drop honest notes — what was harder than expected, what was easier, what was cut and why.

- **Week 1:** Scaffolding a project this size in one go forced architectural discipline I'd usually defer. Writing `ARCHITECTURE.md` *first* exposed the LLM router boundary and the audit-substrate contract before any agent code touched them.

---

## Roadmap

See [ROADMAP.md](../ROADMAP.md) for the week-by-week plan. The Week 13+ shortlist:

- Real hardware integration on a small physical rack.
- Kubernetes deployment manifests.
- Multi-operator RBAC and per-tenant LLM cost isolation.
- Real action library (vendor-specific Redfish + DCGM calls).
- Cross-region replicated state stores.

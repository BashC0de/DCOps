# DCOps Copilot — 10-minute demo script

> The script that runs end-to-end. Time markers are conservative; with a warm cache it runs ~30% faster.

## Pre-flight (off camera)

```
make demo            # all 3 sites up; verify with `make ps`
make seed            # populate KG + sample telemetry
open http://localhost:3000
open http://localhost:8080/docs
```

Have a terminal pane open running `docker compose logs -f forensic-frankfurt sentinel-frankfurt executor-frankfurt rollback-frankfurt`.

---

## 0:00–1:00 · The setup

> "Modern data center ops teams drown in telemetry from heterogeneous sources — Dell iDRAC, NVIDIA DCGM, IPMI, SNMP, environmental sensors — and every incident is investigated from scratch. DCOps Copilot is what happens when you give that team an autonomous co-pilot."

Open the dashboard. Show the fleet view: three sites, sixty racks, all green.

Click into Frankfurt. Show the thermal heatmap — quiet, steady-state.

---

## 1:00–2:30 · The data plane

> "Five specialized agents subscribe to a unified telemetry stream. Every source — Redfish, DCGM, IPMI, SNMP, environmental — normalizes to a single `TelemetryEvent` schema before anything else touches it."

Open a fast terminal: `redis-cli MONITOR | head -20`. Show the topic firehose.

Open `apps/ingestion/schema.py`, highlight the `CanonicalMetric` enum. Mention typo-resistance.

---

## 2:30–4:00 · The incident

```
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
```

Switch to the agent log pane. Narrate as the chain fires:

> "Sentinel sees the ECC ramp first — XGBoost on Backblaze plus a rule layer for GPU XID codes. It publishes a `PredictedFailure` with 82% confidence."

> "Forensic picks it up. It pulls a 5-minute telemetry window from TimescaleDB, queries Neo4j for a 2-hop subgraph around the GPU, retrieves three similar past incidents from ChromaDB, and routes the whole thing to Haiku. Haiku self-rates 0.78 confidence, which is above threshold, so no Sonnet escalation."

> "Optimizer runs OR-Tools bin-packing — it sees the affected rack, finds the four eligible migration targets that satisfy thermal headroom + PDU budget + anti-affinity, and recommends moving the workload."

> "Policy engine evaluates the recommendation — blast radius is 1 device, no blackout window, change-freeze is off. Approved."

> "Executor calls the mocked Redfish migration endpoint. Records pre-action KPIs."

> "Rollback Monitor watches the post-action window for five minutes."

---

## 4:00–5:30 · The dashboard

Switch to `/incidents`. Click into the incident.

Show:
- Timeline (Sentinel → Forensic → Optimizer → Executor → Rollback)
- RCA hypotheses with confidence bars
- Audit lineage tab: every LLM call, model used, token count, USD cost.

> "Every automated action is explainable end-to-end. An action without a valid audit lineage is refused by the executor."

---

## 5:30–7:00 · The digital twin

Open `/twin`. The hall rotates and zooms to the affected rack, glowing.

> "The digital twin isn't decoration. It's the physics engine the Optimizer reasons against — every recommendation is previewed in the twin before it ships."

Drag-rotate the view. Show the heat propagation across neighboring racks.

---

## 7:00–8:00 · Natural-language query

Open `/query`. Type:

> "Which racks ran hottest in Frankfurt yesterday?"

Show the Operator's response: a one-paragraph answer, a Plotly chart of the top 5, and the SQL that was generated.

> "Operator's NL→SQL is Haiku-only — about $0.005 per question."

---

## 8:00–9:00 · Federated intelligence

> "Now the federation payoff. Earlier this week, Sentinel at Singapore learned a new detection rule for PSU efficiency drift in a specific HPE PSU model. The cross-site correlator pushed the rule to Frankfurt and Mumbai as candidates — both sites ran it in shadow mode for 48 hours."

Open the Grafana board "Cross-site rule propagation" — show that Frankfurt's shadow run flagged a degrading PSU one day later that would have been missed otherwise.

> "A failure pattern caught at one site is pre-empted at the others."

---

## 9:00–10:00 · Close

> "Five agents. Three sites. One platform. Built on a 16GB laptop in 12 weeks. 200 benchmark scenarios. Top-1 RCA accuracy of [X]%. LLM cost per incident of [Y] cents. All open source under Apache 2.0."

Final shot: the README hero badge row + the link.

> "Thanks for watching."

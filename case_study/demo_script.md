# DCOps Copilot — 10-minute demo script

> The script that runs end-to-end. Time markers are conservative; with a warm cache it runs ~30% faster.

## Pre-flight (off camera)

```bash
make demo                              # all 3 sites up; verify with `make ps`
docker compose run --rm ollama-init    # pre-pull OSS models so first calls are instant
make seed                              # populate KG + Chroma corpora + sample telemetry
open http://localhost:3000
open http://localhost:8080/docs
```

If you want richer Sentinel ML predictions (optional, not on the critical path):
```bash
bash scripts/download_backblaze.sh
python scripts/train_sentinel.py
docker compose restart sentinel-frankfurt
```

Have a terminal pane open running:
```bash
docker compose logs -f \
  forensic-frankfurt sentinel-frankfurt executor-frankfurt rollback-frankfurt
```

---

## 0:00–1:00 · The setup

> "Modern data center ops teams drown in telemetry from heterogeneous sources — Dell iDRAC, NVIDIA DCGM, IPMI, SNMP, environmental sensors — and every incident is investigated from scratch. DCOps Copilot is what happens when you give that team an autonomous co-pilot — one that runs on a 16 GB laptop, on free local OSS models by default, with no API key required."

Open the dashboard. Show the fleet overview at `/`: three sites, headline KPIs, recent recommendations.

Click into Frankfurt at `/sites/frankfurt`. Show the thermal heatmap — quiet, steady-state.

---

## 1:00–2:30 · The data plane

> "Five specialized agents subscribe to a unified telemetry stream. Every source — Redfish, DCGM, IPMI, SNMP, environmental — normalizes to a single `TelemetryEvent` schema before anything else touches it."

Open a fast terminal: `redis-cli MONITOR | head -20`. Show the topic firehose.

Open `apps/ingestion/schema.py`, highlight the `CanonicalMetric` enum. Mention typo-resistance.

> "The mocks service [show `curl localhost:8090/redfish/v1/Systems | jq .`] is one FastAPI process emulating four vendor-specific schemas. It saved us a week of yak-shaving."

---

## 2:30–4:00 · The incident

```bash
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
```

Switch to the agent log pane. Narrate as the chain fires:

> "Sentinel sees the ECC ramp first. The rule layer fires on uncorrectable ECC — a deterministic signal — and publishes a `PredictedFailure`. If the trained XGBoost weights are loaded, the rule + model decision fuses and emits the higher-confidence signal."

> "Forensic picks it up. It pulls a 5-minute telemetry window from TimescaleDB, queries Neo4j for a 2-hop subgraph around the GPU via `POWERED_BY` / `DEPENDS_ON` / `COOLED_BY` edges, retrieves three similar past incidents from ChromaDB via cross-encoder rerank, and routes the whole thing to the local `qwen2.5:7b` model with a JSON-schema-constrained prompt. The output is validated against the schema, then KG-grounded — every device ID it mentions must exist."

> "Optimizer runs OR-Tools CP-SAT. It sees the affected rack, finds the eligible migration targets that satisfy PDU power cap + thermal headroom + HA anti-affinity, and publishes a `workload_migration` recommendation."

> "Policy engine evaluates the recommendation — blast radius is 1 device, no blackout window, change-freeze is off. Approved."

> "Executor calls the mocked Redfish migration endpoint. Snapshots pre-action KPIs from TimescaleDB."

> "Rollback Monitor watches the post-action window. If the inlet temp regresses past 10%, it auto-calls the revert endpoint. If KPIs hold, it commits."

---

## 4:00–5:30 · The dashboard

Switch to `/incidents`. Click into the new incident. The detail panel renders:

- Ranked hypotheses with confidence
- Affected devices
- LLM model used + cost ($0.00 on the OSS path)
- Audit-lineage pointer

> "Every automated action is explainable end-to-end. The audit substrate is content-addressed by SHA-256 — re-publishing the same `CallRecord` overwrites with identical content. No duplicate-detection logic needed anywhere."

Show `curl localhost:9001` (MinIO console) → the `dcops-artifacts/audit/<YYYY>/<MM>/<DD>/<sha256>.json` objects.

---

## 5:30–7:00 · The digital twin

Open `/twin`. Site selector → Frankfurt. The hall renders with racks colored by inlet temperature.

> "The digital twin renders the actual Neo4j topology — racks placed by their `[row, col]` field, colored by live inlet temperature from TimescaleDB. After the injected failure, the affected rack glows."

Drag-rotate. Hover a rack — tooltip shows inlet/outlet/device count.

> "Color ramp: blue cool, green ok, amber warn, red hot. Same ramp as the per-site thermal heatmap, by design."

---

## 7:00–8:00 · Natural-language query

Open `/query`. Click one of the example chips:

> "Which racks ran hottest in Frankfurt over the last hour?"

Hit Ask. Show the Operator's response:
- One-paragraph answer
- The SQL it generated (validated SELECT-only by Pydantic + Timescale read-only transaction)
- A Plotly chart of the result
- The runbook sources that informed the answer (with cross-encoder rerank scores)

> "Operator's NL→SQL runs on `qwen2.5-coder:3b` locally — $0 per question on the OSS path. With the optional Anthropic backend, the same path costs about $0.005 per question on Haiku."

---

## 8:00–9:00 · Federated intelligence

> "Now the federation payoff."

```bash
make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
# Wait 60s, repeat 2 more times (correlator threshold = 3)
```

Switch to `curl http://localhost:8080/federation/candidates/singapore | jq .`

> "The cross-site correlator watches `predictions.failure` across every site. Once a (failure-kind, origin-site) crosses the threshold — three hits at confidence > 0.85 within an hour — it broadcasts a `RuleCandidate` to the other sites, with `shadow_until = now + 48 hours`. Receiving sites enable the rule in shadow mode."

Show the candidate landing in Singapore + Mumbai with the 48h window.

> "A failure pattern caught at one site is pre-empted at the others."

---

## 9:00–10:00 · Close

Open `case_study/benchmark_report.html` produced by `make bench`. Show the headline metrics table:

> "Five operational agents. Three sites. One platform. Built on a 16 GB laptop in 12 weeks. 200 benchmark scenarios. Free local OSS by default — paid LLM optional. Apache 2.0."

Show the README hero badge row + the GitHub link.

> "Thanks for watching."

---

## Recovery playbook (if things go sideways live)

| If… | Then… |
|---|---|
| `make demo` is slow to come up | Show `make ps`, point to TimescaleDB+Neo4j health — they take ~30s |
| First LLM call is slow | Mention Ollama cold-load (~10s for 7B model); the next calls are fast |
| Forensic doesn't fire | Check `docker logs dcops-forensic-frankfurt` — likely Chroma not seeded; `make seed` |
| Dashboard route shows degraded | The route returns 200 with `status=degraded` — data plane is up, just empty; re-inject |
| Cross-site demo doesn't propagate | Correlator needs 3 hits at conf > 0.85; inject 3× to trigger |

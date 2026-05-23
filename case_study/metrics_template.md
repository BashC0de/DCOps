# Benchmark metrics — template

> Fill this in from the output of `make bench`. Each row maps 1-1 to a
> headline target in [README.md](../README.md) and to the `TARGETS` map in
> [benchmarks/report.py](../benchmarks/report.py), so this document and the
> auto-generated `case_study/benchmark_report.html` tell the same story.

## Headline

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| Predictive precision @ 24h | > 0.80 | __ | __ |
| RCA top-1 accuracy | > 0.70 | __ | __ |
| Mean time to detect (s) | < 60 | __ | __ |
| p95 time to detect (s) | < 120 | __ | __ |
| LLM cost per incident (USD) | < $0.02 | __ | __ |
| Action recommendation recall | > 0.70 | __ | __ |
| Federation propagation rate | > 0.80 | __ | __ |

> Verdict column comes straight from the HTML report (OK / MISS / no data).

## Per-category breakdown

| Category | N | Detected | RCA top-1 | Mean detect (s) | Action recall |
|---|---|---|---|---|---|
| gpu | __ | __ | __ | __ | __ |
| psu | __ | __ | __ | __ | __ |
| thermal | __ | __ | __ | __ | __ |
| cooling | __ | __ | __ | __ | __ |
| network | __ | __ | __ | __ | __ |
| storage | __ | __ | __ | __ | __ |
| multi | __ | __ | __ | __ | __ |
| federated | __ | __ | __ | __ | __ |

## LLM cost analysis

> Per-call costs are written to the `audit.events` Redis Stream (and from
> there to `dcops-artifacts/audit/...` in MinIO). On the default Ollama
> backend every row's `USD` column is 0.0; on the optional Anthropic backend
> the numbers reflect real per-token pricing.

| Scope | Calls (incidents) | Cost total (USD) | Cost / incident (USD) |
|---|---|---|---|
| All scenarios | __ | __ | __ |
| gpu category | __ | __ | __ |
| psu category | __ | __ | __ |
| thermal category | __ | __ | __ |
| cooling category | __ | __ | __ |
| network category | __ | __ | __ |
| storage category | __ | __ | __ |
| multi category | __ | __ | __ |
| federated category | __ | __ | __ |

## How this maps to the source code

| Headline row | Code |
|---|---|
| Predictive precision @ 24h | `_aggregate()` in [benchmarks/report.py](../benchmarks/report.py) — `len(detected) / n` |
| RCA top-1 accuracy | `_aggregate()` — `len(rca_hits) / n`; match via `_rca_match()` in [benchmarks/runner.py](../benchmarks/runner.py) |
| Mean / p95 time to detect | `statistics.mean(latencies)` / `_percentile(latencies, 0.95)` |
| LLM cost per incident | `sum(llm_cost_usd) / n` (always 0 on Ollama backend) |
| Action recommendation recall | Per-scenario `(expected ∩ proposed) / expected`, averaged |
| Federation propagation rate | `propagated / len(federated)` over scenarios whose name starts with `gen_federated_` |

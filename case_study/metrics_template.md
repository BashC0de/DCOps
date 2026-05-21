# Benchmark metrics — template

> Fill this in from the output of `make bench` (Week 11+). Each row maps 1-1 to
> a target in README.md so the document and the report tell the same story.

## Headline

| Metric | Target | Measured | Notes |
|---|---|---|---|
| Predictive precision @ 24h | > 0.80 | __ | from `bench.report` precision row |
| Predictive recall @ 24h | > 0.70 | __ | |
| RCA top-1 accuracy | > 0.70 | __ | |
| RCA top-3 accuracy | > 0.85 | __ | |
| Mean time to detect (s) | < 60 | __ | |
| Mean time to remediate (s) | < 300 | __ | wall-clock incident open → action verified |
| LLM cost per incident (USD) | < $0.02 | __ | avg over all 200 scenarios |
| Rollback false-positive rate | < 5% | __ | rollbacks where the action was actually fine |
| Cross-site rule propagation success @ 48h | > 60% | __ | propagated rules whose shadow window flagged ≥ 1 true positive |

## Breakdown by failure family

| Family | N | Detected | RCA top-1 | Avg latency (s) | Avg LLM cost |
|---|---|---|---|---|---|
| GPU ECC | __ | __ | __ | __ | __ |
| PSU degradation | __ | __ | __ | __ | __ |
| CRAC failure | __ | __ | __ | __ | __ |
| Thermal runaway | __ | __ | __ | __ | __ |
| Switch cascade | __ | __ | __ | __ | __ |
| Cross-site correlated | __ | __ | __ | __ | __ |

## LLM cost by agent

| Agent | Calls | Total tokens in | Total tokens out | Sonnet share | USD |
|---|---|---|---|---|---|
| Forensic | __ | __ | __ | __ | __ |
| Operator | __ | __ | __ | __ | __ |
| Vision | __ | __ | __ | __ | __ |
| Sentinel (explain only) | __ | __ | __ | __ | __ |

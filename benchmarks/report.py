"""Benchmark report renderer.

Reads `case_study/benchmark_results.json` and emits a single-file HTML
report with headline metrics + per-category breakdowns + LLM cost
analysis. The headline metrics map to the targets in README.md.

Run after `benchmarks/runner.py`:
    python -m benchmarks.report --input case_study/benchmark_results.json
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402

log = get_logger("bench.report")


# Headline targets — from README.md.
TARGETS = {
    "predictive_precision":     ("Predictive precision @ 24h horizon", "> 0.80"),
    "rca_top1":                 ("RCA top-1 accuracy",                 "> 0.70"),
    "mttd":                     ("Mean time to detect (s)",            "< 60"),
    "p95_mttd":                 ("p95 time to detect (s)",             "< 120"),
    "llm_cost_per_incident":    ("LLM cost per incident (USD)",        "< $0.02"),
    "action_recall":            ("Action recommendation recall",       "> 0.70"),
    "federation_propagation":   ("Federation propagation rate",        "> 0.80"),
}


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>DCOps Copilot — Benchmark Report</title>
  <style>
    body {{ font: 14px/1.5 system-ui, -apple-system, sans-serif; max-width: 1080px; margin: 2rem auto; padding: 0 1rem; color: #0f172a; }}
    h1, h2 {{ font-weight: 600; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .subtitle {{ color: #475569; margin-top: 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ padding: .5rem .75rem; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; font-weight: 600; }}
    td.metric, th.metric {{ font-variant-numeric: tabular-nums; text-align: right; }}
    .ok {{ color: #15803d; font-weight: 600; }}
    .miss {{ color: #b91c1c; font-weight: 600; }}
    .pending {{ color: #b45309; }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-family: ui-monospace, monospace; background: #e2e8f0; color: #334155; }}
    code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-family: ui-monospace, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>DCOps Copilot — Benchmark Report</h1>
  <p class="subtitle">{summary}</p>

  <h2>Headline metrics</h2>
  <table>
    <thead>
      <tr><th>Metric</th><th>Target</th><th class="metric">Measured</th><th>Status</th></tr>
    </thead>
    <tbody>{headline_rows}</tbody>
  </table>

  <h2>Per-category breakdown</h2>
  <table>
    <thead>
      <tr><th>Category</th><th class="metric">N</th><th class="metric">Detected</th><th class="metric">RCA top-1</th><th class="metric">Mean detect (s)</th><th class="metric">Action recall</th></tr>
    </thead>
    <tbody>{category_rows}</tbody>
  </table>

  <h2>LLM cost analysis</h2>
  <table>
    <thead>
      <tr><th>Scope</th><th class="metric">Calls (incidents)</th><th class="metric">Cost total (USD)</th><th class="metric">Cost / incident (USD)</th></tr>
    </thead>
    <tbody>{cost_rows}</tbody>
  </table>

  <h2>Per-scenario detail</h2>
  <table>
    <thead>
      <tr><th>Scenario</th><th>Site</th><th>Category</th><th>Detected</th><th class="metric">Latency (s)</th><th>RCA top-1</th><th>Actions proposed</th><th class="metric">LLM cost</th></tr>
    </thead>
    <tbody>{detail_rows}</tbody>
  </table>
</body>
</html>
"""


def _verdict(measured: float, target: str) -> str:
    """Compare a measured value against a `> 0.8` / `< 60` string target."""
    target = target.strip()
    try:
        if target.startswith(">"):
            threshold = float(target.lstrip(">").lstrip("$ ").strip())
            return "ok" if measured > threshold else "miss"
        if target.startswith("<"):
            threshold = float(target.lstrip("<").lstrip("$ ").strip())
            return "ok" if measured < threshold else "miss"
    except ValueError:
        pass
    return "pending"


def _fmt(value: float | None, *, fmt: str = ".3f") -> str:
    if value is None:
        return "—"
    return format(value, fmt)


def _aggregate(results: list[dict]) -> dict[str, float | None]:
    n = len(results)
    if n == 0:
        return {k: None for k in TARGETS.keys()}

    detected = [r for r in results if r.get("detected")]
    latencies = [r["detection_latency_sec"] for r in detected if r.get("detection_latency_sec") is not None]
    rca_hits = [r for r in results if r.get("rca_top1_match")]
    federated = [r for r in results if r.get("name", "").startswith("gen_federated_")]
    propagated = [r for r in federated if r.get("candidate_propagated")]

    # Action recall: did we propose at least the expected kinds?
    def _recall(r: dict) -> float:
        expected = set(r.get("expected_actions", []))
        if not expected:
            return 1.0    # nothing expected → trivially satisfied
        proposed = set(r.get("actions_proposed", []))
        return len(expected & proposed) / len(expected)

    recalls = [_recall(r) for r in results]
    total_cost = sum(float(r.get("llm_cost_usd", 0.0) or 0.0) for r in results)

    return {
        "predictive_precision":   len(detected) / n,
        "rca_top1":               len(rca_hits) / n,
        "mttd":                   statistics.mean(latencies) if latencies else None,
        "p95_mttd":               _percentile(latencies, 0.95) if latencies else None,
        "llm_cost_per_incident":  total_cost / n,
        "action_recall":          statistics.mean(recalls) if recalls else None,
        "federation_propagation": (len(propagated) / len(federated)) if federated else None,
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round(p * (len(s) - 1)))
    return s[k]


def _headline_rows(agg: dict[str, float | None]) -> str:
    parts = []
    for key, (label, target) in TARGETS.items():
        value = agg.get(key)
        if value is None:
            parts.append(
                f"<tr><td>{label}</td><td>{target}</td>"
                f"<td class='metric'>—</td><td class='pending'>no data</td></tr>"
            )
            continue
        verdict = _verdict(value, target)
        fmt = ".3f" if key not in ("mttd", "p95_mttd") else ".1f"
        parts.append(
            f"<tr><td>{label}</td><td>{target}</td>"
            f"<td class='metric'>{_fmt(value, fmt=fmt)}</td>"
            f"<td class='{verdict}'>{verdict.upper()}</td></tr>"
        )
    return "\n".join(parts)


def _category_rows(results: list[dict]) -> str:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "other")].append(r)

    out_rows = []
    for cat in sorted(by_cat.keys()):
        rs = by_cat[cat]
        detected = [r for r in rs if r.get("detected")]
        rca_hits = [r for r in rs if r.get("rca_top1_match")]
        latencies = [
            r["detection_latency_sec"] for r in detected
            if r.get("detection_latency_sec") is not None
        ]
        recalls = [
            (lambda r: (
                1.0 if not r.get("expected_actions")
                else len(set(r.get("expected_actions", [])) &
                         set(r.get("actions_proposed", []))) / len(r.get("expected_actions", []))
            ))(r)
            for r in rs
        ]
        out_rows.append(
            f"<tr><td>{html.escape(cat)}</td>"
            f"<td class='metric'>{len(rs)}</td>"
            f"<td class='metric'>{len(detected)}/{len(rs)}</td>"
            f"<td class='metric'>{len(rca_hits)}/{len(rs)}</td>"
            f"<td class='metric'>{statistics.mean(latencies):.1f}" if latencies else "<td class='metric'>—"
            f"</td>"
            f"<td class='metric'>{statistics.mean(recalls):.2f}" if recalls else "<td class='metric'>—"
            f"</td></tr>"
        )
    return "\n".join(out_rows)


def _cost_rows(results: list[dict]) -> str:
    total = sum(float(r.get("llm_cost_usd", 0.0) or 0.0) for r in results)
    n_with_cost = sum(1 for r in results if r.get("llm_cost_usd"))
    per = total / max(1, n_with_cost) if n_with_cost else 0.0
    rows = [
        f"<tr><td>All scenarios</td>"
        f"<td class='metric'>{n_with_cost}</td>"
        f"<td class='metric'>${total:.4f}</td>"
        f"<td class='metric'>${per:.4f}</td></tr>"
    ]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "other")].append(r)
    for cat in sorted(by_cat.keys()):
        rs = by_cat[cat]
        ct = sum(float(r.get("llm_cost_usd", 0.0) or 0.0) for r in rs)
        n = sum(1 for r in rs if r.get("llm_cost_usd"))
        per = ct / max(1, n) if n else 0.0
        rows.append(
            f"<tr><td>{html.escape(cat)}</td>"
            f"<td class='metric'>{n}</td>"
            f"<td class='metric'>${ct:.4f}</td>"
            f"<td class='metric'>${per:.4f}</td></tr>"
        )
    return "\n".join(rows)


def _detail_rows(results: list[dict]) -> str:
    out = []
    for r in results:
        det_cls = "ok" if r.get("detected") else "miss"
        rca_cls = "ok" if r.get("rca_top1_match") else "miss"
        actions = ", ".join(r.get("actions_proposed", [])) or "—"
        latency = r.get("detection_latency_sec")
        latency_str = f"{latency:.1f}" if isinstance(latency, (int, float)) else "—"
        out.append(
            f"<tr>"
            f"<td><code>{html.escape(r.get('name', '?'))}</code></td>"
            f"<td>{html.escape(r.get('site_id', '?'))}</td>"
            f"<td><span class='pill'>{html.escape(r.get('category', '?'))}</span></td>"
            f"<td class='{det_cls}'>{r.get('detected')}</td>"
            f"<td class='metric'>{latency_str}</td>"
            f"<td class='{rca_cls}'>{r.get('rca_top1_match')}</td>"
            f"<td>{html.escape(actions)}</td>"
            f"<td class='metric'>${r.get('llm_cost_usd', 0.0):.4f}</td>"
            f"</tr>"
        )
    return "\n".join(out)


def render(results: list[dict]) -> str:
    agg = _aggregate(results)
    n = len(results)
    detected = sum(1 for r in results if r.get("detected"))
    rca_hits = sum(1 for r in results if r.get("rca_top1_match"))
    summary = (
        f"Ran {n} scenarios. {detected} detected · {rca_hits} RCA top-1 hits · "
        f"mean detect "
        f"{_fmt(agg.get('mttd'), fmt='.1f') if agg.get('mttd') is not None else '—'}s · "
        f"cost ${_fmt(agg.get('llm_cost_per_incident'), fmt='.4f')} per scenario."
    )
    return HTML_TEMPLATE.format(
        summary=summary,
        headline_rows=_headline_rows(agg),
        category_rows=_category_rows(results),
        cost_rows=_cost_rows(results),
        detail_rows=_detail_rows(results),
    )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="case_study/benchmark_results.json")
    parser.add_argument("--output", default="case_study/benchmark_report.html")
    args = parser.parse_args()

    results = json.loads(Path(args.input).read_text())
    html_str = render(results)
    Path(args.output).write_text(html_str)
    log.info("bench.report.done", output=args.output)


__all__ = ["render", "_aggregate", "_verdict", "TARGETS"]


if __name__ == "__main__":
    main()

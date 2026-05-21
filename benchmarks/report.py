"""Benchmark report renderer.

Reads `case_study/benchmark_results.json` and emits a single-file HTML report
with the headline metrics table from README.md.

Ships: Week 11 (see ROADMAP.md).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.shared.logging import configure_logging, get_logger  # noqa: E402

log = get_logger("bench.report")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>DCOps Copilot — Benchmark Report</title>
  <style>
    body {{ font: 14px/1.5 system-ui, -apple-system, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
    h1, h2 {{ font-weight: 600; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ padding: .5rem .75rem; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .ok {{ color: #15803d; }}
    .miss {{ color: #b91c1c; }}
  </style>
</head>
<body>
  <h1>DCOps Copilot — Benchmark Report</h1>
  <p>{summary}</p>
  <h2>Headline metrics</h2>
  <table>
    <tr><th>Metric</th><th>Target</th><th>Measured</th></tr>
    {rows}
  </table>
  <h2>Per-scenario detail</h2>
  <table>
    <tr><th>Scenario</th><th>Detected</th><th>Latency (s)</th><th>RCA top-1</th><th>LLM cost (USD)</th></tr>
    {detail_rows}
  </table>
</body>
</html>
"""


def _row(metric: str, target: str, measured: str) -> str:
    return f"<tr><td>{metric}</td><td>{target}</td><td>{measured}</td></tr>"


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="case_study/benchmark_results.json")
    parser.add_argument("--output", default="case_study/benchmark_report.html")
    args = parser.parse_args()

    results = json.loads(Path(args.input).read_text())
    n = len(results)
    detected = [r for r in results if r["detected"]]
    rca_hits = [r for r in results if r["rca_top1_match"]]
    latencies = [r["detection_latency_sec"] for r in detected if r["detection_latency_sec"] is not None]
    total_cost = sum(r.get("llm_cost_usd", 0.0) for r in results)

    rows = "\n".join([
        _row("Predictive precision @24h", "> 0.80",
             f"{len(detected)}/{n} = {len(detected) / max(1, n):.2f}"),
        _row("RCA top-1 accuracy", "> 0.70",
             f"{len(rca_hits)}/{n} = {len(rca_hits) / max(1, n):.2f}"),
        _row("Mean time to detect (s)", "< 60",
             f"{statistics.mean(latencies):.1f}" if latencies else "—"),
        _row("LLM cost per incident (USD)", "< $0.02",
             f"{total_cost / max(1, n):.4f}"),
    ])

    detail_rows = "\n".join(
        f"<tr><td>{r['name']}</td>"
        f"<td class='{'ok' if r['detected'] else 'miss'}'>{r['detected']}</td>"
        f"<td>{r['detection_latency_sec'] or '—'}</td>"
        f"<td class='{'ok' if r['rca_top1_match'] else 'miss'}'>{r['rca_top1_match']}</td>"
        f"<td>{r.get('llm_cost_usd', 0.0):.4f}</td></tr>"
        for r in results
    )

    html = HTML_TEMPLATE.format(
        summary=f"Ran {n} scenarios. {len(detected)} detected, {len(rca_hits)} RCA top-1 hits.",
        rows=rows,
        detail_rows=detail_rows,
    )
    Path(args.output).write_text(html)
    log.info("bench.report.done", output=args.output)


if __name__ == "__main__":
    main()

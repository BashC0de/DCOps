"use client";

import { useState } from "react";

import { PlotlyChart } from "../../components/PlotlyChart";
import { StatusBadge } from "../../components/StatusBadge";
import { QueryAnswer, postQuery } from "../../lib/api";

const EXAMPLES = [
  "Which racks ran hottest in Frankfurt over the last hour?",
  "Show me total power draw for site frankfurt over the last hour",
  "Are any CPU temps above 85 degrees right now?",
  "Did any GPUs report XID errors in the last 24 hours?",
];

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [site, setSite] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryAnswer | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const answer = await postQuery(question, site || undefined);
      setResult(answer);
    } catch (err) {
      setError(String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Operator query</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Ask a question in plain English. Operator retrieves matching runbooks,
          generates safe SELECT-only SQL, executes against TimescaleDB, and
          returns a chart spec.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-100/60">site:</span>
          {["", "frankfurt", "singapore", "mumbai"].map((s) => (
            <button
              type="button"
              key={s || "any"}
              onClick={() => setSite(s)}
              className={`rounded-full border px-3 py-0.5 text-xs ${
                site === s
                  ? "border-accent-info bg-accent-info/10 text-accent-info"
                  : "border-ink-100/10 text-ink-100/70"
              }`}
            >
              {s || "any"}
            </button>
          ))}
        </div>
        <div className="flex gap-3">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Which racks ran hottest yesterday?"
            className="flex-1 rounded-lg border border-ink-100/10 bg-ink-900/40 px-4 py-2 text-sm outline-none focus:border-accent-info"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="rounded-lg bg-accent-info px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            {loading ? "…" : "Ask"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {EXAMPLES.map((ex) => (
            <button
              type="button"
              key={ex}
              onClick={() => setQuestion(ex)}
              className="rounded-full border border-ink-100/10 px-3 py-0.5 text-ink-100/60 transition hover:border-accent-info/40 hover:text-ink-100"
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {error && (
        <div className="rounded-lg border border-accent-err/30 bg-accent-err/10 p-4 text-sm text-accent-err">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4 rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm">{result.answer_text}</p>
            {result.sources?.length ? (
              <StatusBadge status="info">
                {result.sources.length} source(s)
              </StatusBadge>
            ) : null}
          </div>

          {result.sql_executed && (
            <details className="rounded bg-ink-950 p-3" open>
              <summary className="cursor-pointer text-xs text-ink-100/60">
                SQL executed
              </summary>
              <pre className="mt-2 overflow-x-auto font-mono text-xs">
                {result.sql_executed}
              </pre>
            </details>
          )}

          {result.chart_spec && (
            <div>
              <h3 className="mb-2 text-xs uppercase tracking-wide text-ink-100/60">
                Result
              </h3>
              <PlotlyChart spec={result.chart_spec} />
            </div>
          )}

          {!result.chart_spec && result.metadata?.rows?.length ? (
            <div className="overflow-x-auto">
              <h3 className="mb-2 text-xs uppercase tracking-wide text-ink-100/60">
                Rows
              </h3>
              <table className="min-w-full font-mono text-xs">
                <thead>
                  <tr className="border-b border-ink-100/10 text-left text-ink-100/60">
                    {Object.keys(result.metadata.rows[0] ?? {}).map((k) => (
                      <th key={k} className="px-2 py-1">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.metadata.rows.slice(0, 50).map((r, i) => (
                    <tr key={i} className="border-b border-ink-100/5">
                      {Object.values(r).map((v, j) => (
                        <td key={j} className="px-2 py-1">
                          {String(v ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {result.sources?.length ? (
            <div>
              <h3 className="mb-2 text-xs uppercase tracking-wide text-ink-100/60">
                Runbook sources
              </h3>
              <ul className="space-y-1 font-mono text-xs text-ink-100/70">
                {result.sources.map((s, i) => (
                  <li key={i}>
                    <span className="text-accent-info">{s.id ?? "?"}</span>
                    {s.category && <span> · {s.category}</span>}
                    {typeof s.score === "number" && (
                      <span> · score {s.score.toFixed(2)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

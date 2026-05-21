"use client";

// Natural-language query interface. POSTs to /query (Operator agent).
// Ships full implementation in Week 6 (chart rendering Week 10).

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

interface QueryResult {
  request_id: string;
  question: string;
  answer_text: string;
  sql_executed: string | null;
}

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      setResult((await res.json()) as QueryResult);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Operator query</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Ask a question in plain English. Operator translates to SQL + a chart.
        </p>
      </header>

      <form onSubmit={submit} className="flex gap-3">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Which racks ran hottest in Frankfurt yesterday?"
          className="flex-1 rounded-lg border border-ink-100/10 bg-ink-900/40 px-4 py-2 text-sm outline-none focus:border-accent-info"
        />
        <button
          type="submit"
          disabled={loading || !question}
          className="rounded-lg bg-accent-info px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
        >
          {loading ? "…" : "Ask"}
        </button>
      </form>

      {result && (
        <div className="space-y-3 rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <p className="text-sm">{result.answer_text}</p>
          {result.sql_executed && (
            <pre className="overflow-x-auto rounded bg-ink-950 p-3 font-mono text-xs">
              {result.sql_executed}
            </pre>
          )}
          {/* TODO(week-10): render chart_spec via react-plotly.js */}
        </div>
      )}
    </div>
  );
}

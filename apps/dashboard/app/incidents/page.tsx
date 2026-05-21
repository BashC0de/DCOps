// Incidents timeline + RCA viewer + audit explainability tab.
// Real implementation lands Week 10 alongside the Forensic + Executor agents.

export default function IncidentsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Incidents</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Timeline · root cause hypotheses · full audit lineage · rollback history.
        </p>
      </header>

      <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
        <p className="text-sm text-ink-100/60">
          {/* TODO(week-10): swr query /incidents, render timeline + drilldown panel */}
          Incident stream renders Week 10. Currently you can hit{" "}
          <code className="font-mono text-accent-info">GET /incidents</code> on the API directly.
        </p>
      </div>
    </div>
  );
}

"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { IncidentRow } from "../../components/IncidentRow";
import { StatusBadge } from "../../components/StatusBadge";
import { useIncident, useIncidents } from "../../lib/api";

function IncidentDetailPanel({ incidentId }: { incidentId: string }) {
  const { data, error, isLoading } = useIncident(incidentId);
  if (isLoading) {
    return <p className="text-sm text-ink-100/50">Loading…</p>;
  }
  if (error) {
    return (
      <p className="text-sm text-accent-err">
        Could not load incident: {String(error)}
      </p>
    );
  }
  if (!data) return null;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <StatusBadge status={data.severity} />
        <span className="font-mono text-xs text-ink-100/60">{data.site_id}</span>
      </div>
      <h2 className="text-lg font-semibold">
        {data.top_hypotheses?.[0]?.cause ?? "(no hypothesis)"}
      </h2>
      <dl className="grid grid-cols-2 gap-3 text-xs">
        <Stat label="Opened" value={data.opened_at} />
        <Stat label="Closed" value={data.closed_at ?? "—"} />
        <Stat label="Confidence" value={`${(data.confidence * 100).toFixed(0)}%`} />
        <Stat label="LLM model" value={data.llm_model_used ?? "—"} />
        <Stat
          label="LLM cost"
          value={`$${data.llm_cost_usd.toFixed(4)}`}
        />
        <Stat
          label="Affected devices"
          value={`${data.affected_devices.length}`}
        />
      </dl>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-100/80">
          Ranked hypotheses
        </h3>
        <ol className="space-y-2">
          {data.top_hypotheses?.map((h, i) => (
            <li
              key={i}
              className="rounded border border-ink-100/10 bg-ink-950/60 p-3 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">{h.cause}</span>
                <span className="text-ink-100/60">
                  p={(h.probability * 100).toFixed(0)}%
                </span>
              </div>
              {h.evidence_summary && (
                <p className="mt-1 text-ink-100/60">{h.evidence_summary}</p>
              )}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-100/80">
          Affected devices
        </h3>
        <ul className="font-mono text-xs text-ink-100/60">
          {data.affected_devices.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      </div>
      {data.audit_lineage_endpoint && (
        <p className="text-xs text-ink-100/50">
          Audit lineage:{" "}
          <code className="font-mono text-accent-info">
            {data.audit_lineage_endpoint}
          </code>
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-100/60">{label}</dt>
      <dd className="font-mono text-ink-50">{value}</dd>
    </div>
  );
}

function IncidentsListView() {
  const params = useSearchParams();
  const activeId = params.get("id");

  const [site, setSite] = useState<string | null>(null);
  const { data, error, isLoading } = useIncidents(site ?? undefined, 50);
  const incidents = data?.incidents ?? [];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr,1fr]">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSite(null)}
            className={`rounded-full border px-3 py-1 text-xs ${site == null ? "border-accent-info bg-accent-info/10 text-accent-info" : "border-ink-100/10 text-ink-100/70"}`}
          >
            All sites
          </button>
          {["frankfurt", "singapore", "mumbai"].map((s) => (
            <button
              key={s}
              onClick={() => setSite(s)}
              className={`rounded-full border px-3 py-1 text-xs ${site === s ? "border-accent-info bg-accent-info/10 text-accent-info" : "border-ink-100/10 text-ink-100/70"}`}
            >
              {s}
            </button>
          ))}
        </div>

        {error && (
          <p className="text-sm text-accent-err">
            Failed to load incidents: {String(error)}
          </p>
        )}
        {isLoading && <p className="text-sm text-ink-100/50">Loading…</p>}
        {!isLoading && incidents.length === 0 && (
          <p className="text-sm text-ink-100/50">
            No incidents yet. Try{" "}
            <code className="font-mono text-accent-info">
              make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
            </code>
            .
          </p>
        )}

        <ul className="space-y-2">
          {incidents.map((i) => (
            <li key={i.incident_id}>
              <IncidentRow incident={i} />
            </li>
          ))}
        </ul>
      </div>

      <aside className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
        {activeId ? (
          <IncidentDetailPanel incidentId={activeId} />
        ) : (
          <p className="text-sm text-ink-100/60">
            Select an incident on the left to see ranked hypotheses, affected
            devices, and the audit lineage.
          </p>
        )}
      </aside>
    </div>
  );
}

export default function IncidentsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Incidents</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Timeline · root-cause hypotheses · audit lineage · rollback history.
        </p>
      </header>
      <Suspense fallback={<p className="text-sm text-ink-100/50">Loading…</p>}>
        <IncidentsListView />
      </Suspense>
    </div>
  );
}

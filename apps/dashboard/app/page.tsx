"use client";

import Link from "next/link";

import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { useFleetState, useRecommendations } from "../lib/api";

export default function FleetOverview() {
  const fleet = useFleetState();
  const recs = useRecommendations(undefined, 10);
  const sites = fleet.data?.sites ?? [];

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Fleet overview</h1>
          <p className="mt-1 text-sm text-ink-100/60">
            Live across {sites.length || "—"} sites · refreshed every 5s
          </p>
        </div>
        {fleet.data && (
          <StatusBadge
            status={fleet.data.fleet_status === "ok" ? "ok" : "degraded"}
          >
            {fleet.data.fleet_status}
          </StatusBadge>
        )}
      </header>

      {fleet.error && (
        <div className="rounded-lg border border-accent-err/30 bg-accent-err/10 p-4 text-sm text-accent-err">
          API unreachable: {String(fleet.error)}
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Sites live" value={fleet.data?.n_sites ?? "—"} />
        <MetricCard
          label="Live agents"
          value={fleet.data?.n_live_agents ?? "—"}
          tone={fleet.data?.fleet_status === "degraded" ? "warn" : "ok"}
        />
        <MetricCard
          label="Open incidents · 1h"
          value={fleet.data?.total_incidents_last_hour ?? "—"}
          tone={(fleet.data?.total_incidents_last_hour ?? 0) > 0 ? "warn" : "ok"}
        />
        <MetricCard
          label="Recommendations"
          value={recs.data?.recommendations?.length ?? "—"}
          hint="last 10 emitted"
        />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {sites.length === 0 && (
          <div className="col-span-full rounded-xl border border-dashed border-ink-100/10 p-6 text-sm text-ink-100/60">
            No fleet snapshot yet. Run <code className="font-mono text-accent-info">make dev</code>{" "}
            and wait ~10s for the control plane to materialize{" "}
            <code className="font-mono">fleet:snapshot</code>.
          </div>
        )}
        {sites.map((site) => (
          <Link
            key={site.site_id}
            href={`/sites/${site.site_id}`}
            className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5 transition hover:border-accent-info/40"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm uppercase tracking-wide text-ink-100/70">
                {site.site_id}
              </span>
              <StatusBadge status={site.status === "ok" ? "ok" : "degraded"} />
            </div>
            <p className="mt-3 text-xl font-semibold">
              {site.n_live_agents}{" "}
              <span className="text-sm text-ink-100/60">agents live</span>
            </p>
            <p className="text-xs text-ink-100/60">
              {site.incidents_last_hour} incidents · last hour
            </p>
            {site.missing_agents.length > 0 && (
              <p className="mt-2 text-xs text-accent-warn">
                missing: {site.missing_agents.join(", ")}
              </p>
            )}
          </Link>
        ))}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Recent recommendations</h2>
        {recs.data?.recommendations?.length ? (
          <ul className="space-y-2">
            {recs.data.recommendations.slice(0, 5).map((r) => (
              <li
                key={r.recommendation_id}
                className="rounded-lg border border-ink-100/10 bg-ink-900/40 p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-ink-100/60">
                    {r.site_id} · {r.kind}
                  </span>
                  <StatusBadge status={r.requires_human_approval ? "warn" : "info"}>
                    {r.requires_human_approval ? "needs human" : "auto"}
                  </StatusBadge>
                </div>
                <p className="mt-2 text-sm">
                  {r.target_device_ids.length} target device(s) · confidence{" "}
                  {(r.confidence * 100).toFixed(0)}%
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-100/50">
            No recommendations yet. Inject a failure to trigger Optimizer.
          </p>
        )}
      </section>
    </div>
  );
}

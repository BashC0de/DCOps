"use client";

import Link from "next/link";

import { IncidentRow } from "../../../components/IncidentRow";
import { MetricCard } from "../../../components/MetricCard";
import { PlotlyChart } from "../../../components/PlotlyChart";
import { ThermalHeatmap } from "../../../components/ThermalHeatmap";
import {
  useIncidents,
  useTelemetryRange,
  useTwinState,
} from "../../../lib/api";

interface SitePageProps {
  params: { id: string };
}

export default function SitePage({ params }: SitePageProps) {
  const siteId = params.id;

  const twin = useTwinState(siteId);
  const incidents = useIncidents(siteId, 20);
  const inlet = useTelemetryRange(siteId, "env.inlet.celsius", 3600);
  const power = useTelemetryRange(siteId, "power.draw.watts", 3600);

  const inletSpec = buildLineSpec(inlet.data?.events ?? [], "Inlet (°C)");
  const powerSpec = buildLineSpec(power.data?.events ?? [], "Power (W)");

  const hottest = computeMaxInlet(twin.data?.racks ?? []);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold capitalize">{siteId}</h1>
          <p className="mt-1 text-sm text-ink-100/60">
            {twin.data?.racks?.length ?? 0} racks · live thermal + recent incidents
          </p>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-ink-100/10 px-3 py-1.5 text-xs text-ink-100/70 transition hover:border-accent-info/40"
        >
          ← Fleet
        </Link>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Racks" value={twin.data?.racks?.length ?? "—"} />
        <MetricCard
          label="Incidents · last 24h"
          value={incidents.data?.incidents?.length ?? "—"}
          tone={(incidents.data?.incidents?.length ?? 0) > 0 ? "warn" : "ok"}
        />
        <MetricCard
          label="Hottest rack"
          value={hottest ? `${hottest.inlet_c?.toFixed(1)}°C` : "—"}
          hint={hottest?.id}
          tone={
            hottest && (hottest.inlet_c ?? 0) > 30
              ? "err"
              : hottest && (hottest.inlet_c ?? 0) > 26
              ? "warn"
              : "ok"
          }
        />
        <MetricCard
          label="Telemetry"
          value={inlet.data?.events?.length ?? "—"}
          hint="inlet samples · last hr"
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <h2 className="mb-3 text-sm font-semibold text-ink-100/80">
            Thermal heatmap
          </h2>
          <ThermalHeatmap racks={twin.data?.racks ?? []} />
        </div>
        <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <h2 className="mb-3 text-sm font-semibold text-ink-100/80">
            Recent incidents
          </h2>
          {(incidents.data?.incidents ?? []).length === 0 ? (
            <p className="text-sm text-ink-100/50">No incidents in the last 24h.</p>
          ) : (
            <ul className="space-y-2">
              {incidents.data?.incidents.slice(0, 6).map((i) => (
                <IncidentRow key={i.incident_id} incident={i} />
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-sm font-semibold text-ink-100/80">
            Inlet temperature · last hour
          </h2>
          <PlotlyChart spec={inletSpec} />
        </div>
        <div>
          <h2 className="mb-3 text-sm font-semibold text-ink-100/80">
            Power draw · last hour
          </h2>
          <PlotlyChart spec={powerSpec} />
        </div>
      </section>
    </div>
  );
}

function buildLineSpec(
  rows: { time: string; value_num?: number }[],
  label: string,
) {
  if (!rows.length) return null;
  return {
    data: [
      {
        type: "scatter",
        mode: "lines",
        name: label,
        x: rows.map((r) => r.time),
        y: rows.map((r) => r.value_num ?? null),
        line: { color: "#3b82f6" },
      },
    ],
    layout: {
      title: label,
      xaxis: { title: "time" },
      yaxis: { title: label },
    },
  };
}

function computeMaxInlet(racks: { id: string; inlet_c?: number | null }[]) {
  let best: { id: string; inlet_c?: number | null } | null = null;
  for (const r of racks) {
    if (r.inlet_c == null) continue;
    if (best == null || (best.inlet_c ?? -Infinity) < r.inlet_c) {
      best = r;
    }
  }
  return best;
}

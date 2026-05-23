import Link from "next/link";

import { StatusBadge, StatusKind } from "./StatusBadge";
import { IncidentRow as IncidentRowType } from "../lib/api";

function severityToStatus(s: IncidentRowType["severity"]): StatusKind {
  return s as StatusKind;
}

function fmtTs(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

export function IncidentRow({ incident }: { incident: IncidentRowType }) {
  const top = incident.top_hypotheses?.[0];
  return (
    <Link
      href={`/incidents?id=${incident.incident_id}`}
      className="block rounded-lg border border-ink-100/10 bg-ink-900/40 p-4 transition hover:border-accent-info/40"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge status={severityToStatus(incident.severity)} />
          <span className="font-mono text-xs text-ink-100/60">{incident.site_id}</span>
        </div>
        <span className="text-xs text-ink-100/50">{fmtTs(incident.opened_at)}</span>
      </div>
      <p className="mt-2 text-sm">
        {top?.cause ?? "(no hypothesis)"} —{" "}
        <span className="text-ink-100/60">
          confidence {(incident.confidence * 100).toFixed(0)}%
        </span>
      </p>
      <p className="mt-1 font-mono text-xs text-ink-100/50">
        {incident.affected_devices.slice(0, 3).join(", ")}
        {incident.affected_devices.length > 3 ? ` … +${incident.affected_devices.length - 3}` : ""}
      </p>
    </Link>
  );
}

import clsx from "clsx";

import { TwinRack } from "../lib/api";

// Color ramp: blue (cool) → green (nominal) → amber → red (hot).
// Inlet temp targets: ~22°C cool, ~30°C warm, ~35°C+ hot.
function tempColor(c?: number | null): string {
  if (c == null) return "bg-ink-100/10";
  if (c < 22) return "bg-accent-info/40";
  if (c < 26) return "bg-accent-ok/50";
  if (c < 30) return "bg-accent-warn/50";
  return "bg-accent-err/60";
}

export function ThermalHeatmap({ racks }: { racks: TwinRack[] }) {
  if (!racks.length) {
    return (
      <p className="text-sm text-ink-100/50">
        No rack telemetry yet. The simulator + ingestion pipeline need a few seconds to fill.
      </p>
    );
  }
  // Group by hall for clearer layout.
  const byHall = racks.reduce<Record<string, TwinRack[]>>((acc, r) => {
    (acc[r.hall_id] ??= []).push(r);
    return acc;
  }, {});
  return (
    <div className="space-y-4">
      {Object.entries(byHall).map(([hall, hallRacks]) => (
        <div key={hall}>
          <p className="mb-2 font-mono text-xs text-ink-100/60">{hall}</p>
          <div className="grid grid-cols-5 gap-2 sm:grid-cols-10">
            {hallRacks.map((r) => (
              <div
                key={r.id}
                title={`${r.id} · inlet ${r.inlet_c?.toFixed(1) ?? "?"}°C · outlet ${r.outlet_c?.toFixed(1) ?? "?"}°C`}
                className={clsx(
                  "flex h-14 flex-col items-center justify-center rounded border border-ink-100/10 text-[10px] transition hover:border-accent-info/40",
                  tempColor(r.inlet_c),
                )}
              >
                <span className="font-mono text-ink-50/90">
                  {r.id.split("-").pop()}
                </span>
                {r.inlet_c != null && (
                  <span className="text-ink-50/90">{r.inlet_c.toFixed(1)}°</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

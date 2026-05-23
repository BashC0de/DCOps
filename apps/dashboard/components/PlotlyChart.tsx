"use client";

import dynamic from "next/dynamic";
import type { Layout, PlotData } from "plotly.js";

// next/dynamic prevents Plotly from being imported during SSR (it accesses
// `window` at module load time).
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const DARK_LAYOUT: Partial<Layout> = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#e3e8ee" },
  margin: { l: 50, r: 20, t: 40, b: 40 },
  xaxis: { gridcolor: "rgba(255,255,255,0.05)", zerolinecolor: "rgba(255,255,255,0.1)" },
  yaxis: { gridcolor: "rgba(255,255,255,0.05)", zerolinecolor: "rgba(255,255,255,0.1)" },
  showlegend: true,
};

export function PlotlyChart({
  spec,
  height = 320,
}: {
  spec: { data: unknown[]; layout?: Record<string, unknown> } | null | undefined;
  height?: number;
}) {
  if (!spec || !Array.isArray(spec.data) || spec.data.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-ink-100/10 p-6 text-sm text-ink-100/50">
        No chart data.
      </div>
    );
  }
  const layout: Partial<Layout> = {
    ...DARK_LAYOUT,
    ...((spec.layout ?? {}) as Partial<Layout>),
    autosize: true,
  };
  return (
    <div className="rounded-lg border border-ink-100/10 bg-ink-900/40 p-3">
      <Plot
        data={spec.data as Partial<PlotData>[]}
        layout={layout}
        style={{ width: "100%", height }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
      />
    </div>
  );
}

// Per-site drilldown with thermal heatmap.
// Ships full implementation in Week 10. Until then, renders the site id + a
// placeholder for the thermal grid component.

interface SitePageProps {
  params: { id: string };
}

export default function SitePage({ params }: SitePageProps) {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold capitalize">{params.id}</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Per-site drilldown · racks, devices, thermal heatmap, recent incidents.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <h2 className="text-sm font-semibold text-ink-100/80">Thermal heatmap</h2>
          <p className="mt-2 text-xs text-ink-100/50">
            {/* TODO(week-10): grid of rack cells colored by max inlet temp */}
            Heatmap renders Week 10 with live `/twin/state` data.
          </p>
        </div>

        <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
          <h2 className="text-sm font-semibold text-ink-100/80">Recent incidents</h2>
          <p className="mt-2 text-xs text-ink-100/50">
            {/* TODO(week-10): swr query /incidents?site={params.id} */}
            Incident list renders Week 10.
          </p>
        </div>
      </div>
    </div>
  );
}

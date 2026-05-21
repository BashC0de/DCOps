import Link from "next/link";

// Fleet overview — Week 10 fills this with live data from /api fleet snapshot.
// TODO(week-10): SWR query against `${NEXT_PUBLIC_API_BASE_URL}/twin/state?...` per site.

const SITES = [
  { id: "frankfurt", region: "eu-central-1", racks: 20 },
  { id: "singapore", region: "ap-southeast-1", racks: 20 },
  { id: "mumbai", region: "ap-south-1", racks: 20 },
];

export default function FleetOverview() {
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">Fleet overview</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          Three sites · 60 racks · live telemetry · autonomous remediation
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {SITES.map((site) => (
          <Link
            key={site.id}
            href={`/sites/${site.id}`}
            className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5 transition hover:border-accent-info/40"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm uppercase tracking-wide text-ink-100/70">
                {site.id}
              </span>
              <span className="rounded-full bg-accent-ok/15 px-2 py-0.5 text-xs text-accent-ok">
                healthy
              </span>
            </div>
            <p className="mt-2 text-xl font-semibold">{site.racks} racks</p>
            <p className="text-xs text-ink-100/50">{site.region}</p>
          </Link>
        ))}
      </section>

      <section className="rounded-xl border border-dashed border-ink-100/10 p-6 text-sm text-ink-100/60">
        <p>
          <strong className="text-ink-100/80">Headline metrics</strong> — populated in Week 10.
          Open <code className="font-mono text-accent-info">/incidents</code> for the timeline or
          inject a failure with <code className="font-mono text-accent-info">make inject</code>.
        </p>
      </section>
    </div>
  );
}

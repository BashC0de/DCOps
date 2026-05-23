import clsx from "clsx";

export function MetricCard({
  label,
  value,
  hint,
  tone = "info",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "info" | "warn" | "err" | "ok";
}) {
  const accent: Record<typeof tone, string> = {
    info: "text-accent-info",
    warn: "text-accent-warn",
    err:  "text-accent-err",
    ok:   "text-accent-ok",
  };
  return (
    <div className="rounded-xl border border-ink-100/10 bg-ink-900/40 p-5">
      <p className="text-xs uppercase tracking-wide text-ink-100/60">{label}</p>
      <p className={clsx("mt-2 text-2xl font-semibold", accent[tone])}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-100/50">{hint}</p>}
    </div>
  );
}

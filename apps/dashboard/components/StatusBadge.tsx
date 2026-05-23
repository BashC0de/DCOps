import clsx from "clsx";

export type StatusKind =
  | "ok"
  | "healthy"
  | "degraded"
  | "warn"
  | "error"
  | "critical"
  | "info"
  | "empty";

const STYLE: Record<StatusKind, string> = {
  ok:       "bg-accent-ok/15 text-accent-ok",
  healthy:  "bg-accent-ok/15 text-accent-ok",
  degraded: "bg-accent-warn/15 text-accent-warn",
  warn:     "bg-accent-warn/15 text-accent-warn",
  error:    "bg-accent-err/15 text-accent-err",
  critical: "bg-accent-err/20 text-accent-err",
  info:     "bg-accent-info/15 text-accent-info",
  empty:    "bg-ink-100/10 text-ink-100/60",
};

export function StatusBadge({
  status,
  children,
}: {
  status: StatusKind;
  children?: React.ReactNode;
}) {
  const label = children ?? status;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        STYLE[status] ?? STYLE.info,
      )}
    >
      {label}
    </span>
  );
}

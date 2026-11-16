import type { InputHTMLAttributes, ReactNode } from "react";

/** Rounded ink panel used across dashboards and auth cards. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border border-white/10 bg-ink-2/80 backdrop-blur ${className}`}
    >
      {children}
    </div>
  );
}

/** Small uppercase status chip. */
export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "mint" | "amber" | "aqua";
}) {
  const tones = {
    neutral: "border-white/20 text-white/60",
    mint: "border-mint/40 text-mint",
    amber: "border-amber/40 text-amber",
    aqua: "border-aqua/40 text-aqua",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-[var(--radius-chip)] border px-2.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wider ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** Labelled text input. */
export function Field({
  label,
  hint,
  className = "",
  ...rest
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
        {label}
      </span>
      <input
        className={`w-full rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper placeholder:text-white/30 focus:border-mint focus:outline-none focus:ring-1 focus:ring-mint/50 ${className}`}
        {...rest}
      />
      {hint ? <span className="mt-1 block text-xs text-white/40">{hint}</span> : null}
    </label>
  );
}

/** Inline alert for form/flow errors and notices. */
export function Alert({
  children,
  tone = "error",
}: {
  children: ReactNode;
  tone?: "error" | "success" | "info";
}) {
  if (!children) return null;
  const tones = {
    error: "border-amber/40 bg-amber/10 text-amber",
    success: "border-mint/40 bg-mint/10 text-mint",
    info: "border-aqua/30 bg-aqua/10 text-aqua",
  } as const;
  return (
    <div
      role="alert"
      className={`rounded-[var(--radius-tile)] border px-3.5 py-2.5 text-sm ${tones[tone]}`}
    >
      {children}
    </div>
  );
}

/** A labelled metric used on the dashboard/admin headers. */
export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-tile)] border border-white/10 bg-ink-3/60 px-4 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-wider text-white/45">
        {label}
      </div>
      <div className="display mt-1 text-2xl text-paper">{value}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-white/60">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-mint" />
      {label ? <span className="font-mono text-xs uppercase tracking-wider">{label}</span> : null}
    </div>
  );
}

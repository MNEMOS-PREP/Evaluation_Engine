/**
 * M13 primitives.
 *
 * Module-local on purpose. `@ai/core` owns the PROVENANCE components — what a
 * sourced fact looks like — because those are a platform contract and a
 * nineteenth copy is how they drift. Layout and chrome are not a contract;
 * they are this module's job, and keeping them here means the design can move
 * without a version bump in another repo.
 */

import type { ReactNode } from "react";

import type { Agreement } from "../types";

/* ------------------------------------------------------------------ */
/*  Structure                                                          */
/* ------------------------------------------------------------------ */

export function Section({
  label,
  title,
  meta,
  action,
  children,
}: {
  label?: string;
  title?: string;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mb-12">
      {(label || title || action) && (
        <header className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            {label && <p className="rule-label">{label}</p>}
            {title && <h2 className="text-section font-semibold text-ink">{title}</h2>}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {meta && <span className="provenance">{meta}</span>}
            {action}
          </div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Panel({
  children,
  className = "",
  tone = "plain",
}: {
  children: ReactNode;
  className?: string;
  tone?: "plain" | "sunken";
}) {
  const bg = tone === "sunken" ? "bg-surface-sunken" : "bg-surface";
  return <div className={`panel ${bg} ${className}`}>{children}</div>;
}

export function Rows({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-line">{children}</div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-xs text-ink-soft">{label}</span>
      <span className="provenance text-right break-all">{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Controls                                                           */
/* ------------------------------------------------------------------ */

export function Btn({
  children,
  variant = "secondary",
  size = "md",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const variants = {
    primary: "bg-brand text-white hover:bg-brand-hover",
    secondary: "border border-line bg-surface text-ink hover:border-line-strong",
    ghost: "text-ink-soft hover:bg-surface-sunken hover:text-ink",
    danger: "border border-contested-line bg-contested-soft text-contested hover:border-contested",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-1.5 text-sm" };
  // `children` was destructured above and then never rendered, so every one of
  // this module's eighteen buttons - "Score it", "Resolve", "Drain" - drew as an
  // empty pill. Found 2026-10-03 from a screenshot; nothing in the suite looks
  // at a button's label.
  return (
    <button {...props} className={`${base} ${variants[variant]} ${sizes[size]}`}>
      {children}
    </button>
  );
}

export function TextArea({
  label,
  hint,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string }) {
  return (
    <label className="block">
      <span className="rule-label">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-ink-soft">{hint}</span>}
      <textarea
        {...props}
        className="mt-1.5 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-brand-line"
      />
    </label>
  );
}

export function Select({
  label,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className="block">
      <span className="rule-label">{label}</span>
      <select
        {...props}
        className="mt-1.5 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-brand-line"
      >
        {children}
      </select>
    </label>
  );
}

/* ------------------------------------------------------------------ */
/*  States                                                             */
/* ------------------------------------------------------------------ */

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`h-4 ${i % 3 === 2 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-panel border border-dashed border-line-strong px-6 py-10 text-center">
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-sm text-ink-soft">{children}</div>}
      {action && <div className="mt-4 flex justify-center gap-2">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Badges                                                             */
/* ------------------------------------------------------------------ */

export function Pill({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "confirmed" | "reported" | "contested" | "brand";
  title?: string;
}) {
  const tones = {
    neutral: "border-line bg-surface-sunken text-ink-soft",
    confirmed: "border-confirmed-line bg-confirmed-soft text-confirmed",
    reported: "border-reported-line bg-reported-soft text-reported",
    contested: "border-contested-line bg-contested-soft text-contested",
    brand: "border-brand-line bg-brand-soft text-brand",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * How much the ensemble agreed — NOT how confident the model said it was.
 *
 * `model_confidence` is a self-report; it feeds ECE and a student cannot act
 * on it (§8.1). This is derived from spread across independent members, and
 * a single-member run is never "high" — one evaluator agreeing with itself is
 * not evidence, so `agreement_for(0, members=1)` returns `medium` on purpose.
 */
export function AgreementBadge({
  agreement,
  spread,
}: {
  agreement: Agreement | null | undefined;
  spread?: number;
}) {
  if (!agreement) return null;
  const tone = { high: "confirmed", medium: "reported", low: "contested" } as const;
  const words = {
    high: "evaluators agreed",
    medium: "some disagreement",
    low: "evaluators disagreed",
  };
  return (
    <Pill
      tone={tone[agreement]}
      title={spread === undefined ? undefined : `spread ${spread} level(s), max − min`}
    >
      {words[agreement]}
      {spread !== undefined && spread > 0 && (
        <span className="provenance" data-numeric>
          ±{spread}
        </span>
      )}
    </Pill>
  );
}

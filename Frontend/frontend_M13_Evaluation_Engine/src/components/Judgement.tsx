/**
 * One dimension's judgement — and the only place in this app that decides
 * whether a number may be rendered.
 *
 * §6.7's display gate, stated as code: `calibrated_score` is null unless a
 * fitted mapping exists for this (dimension, round_type, ensemble_config) AND
 * that fit passed every threshold. Null means the student sees the reasoning
 * and the evidence and no number — not a dash, not a greyed-out digit, not the
 * raw score "just for now". §2.4's sentence goes in its place.
 *
 * Concentrating that here is the point. A gate applied by seven components is
 * a gate that six of them apply and the seventh forgets in month four, and the
 * failure is invisible until a placement cell asks what the number means.
 *
 * The developer view is a real switch, not a disclaimer beside the number
 * (see `ui/devMode.ts`).
 */

import { useState } from "react";

import type { DimensionScore, DrawerDimension, RubricDimension } from "../types";
import { AgreementBadge, Panel, Pill } from "../ui/primitives";

export const GATE_NOTE =
  "We're not showing a number here yet — our scoring on this dimension isn't accurate enough to be worth a number.";

/** `kp_3` alone is an id; `[kp_3] Says the worst case…` carries its wording. */
function visibleMissing(points: string[], devMode: boolean): string[] {
  if (devMode) return points;
  return points
    .map((point) => point.replace(/^\[?kp_\d+\]?\s*/i, "").trim())
    .filter(Boolean);
}

export function Judgement({
  drawer,
  score,
  rubricDimension,
  spread,
  devMode,
  active,
  onToggle,
}: {
  drawer: DrawerDimension;
  /** The stored score, when the full evaluation is loaded beside the drawer. */
  score?: DimensionScore;
  rubricDimension?: RubricDimension;
  spread?: number;
  devMode: boolean;
  active: boolean;
  onToggle: () => void;
}) {
  const [showAnchors, setShowAnchors] = useState(false);
  const displayable = drawer.calibrated_score !== null;
  const title = rubricDimension?.name ?? drawer.dimension_key;

  return (
    <Panel
      className={`px-4 py-3.5 transition-colors ${
        active ? "border-quote-line" : ""
      }`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={active}
          className="text-left text-sm font-semibold text-ink hover:text-brand"
          title={
            drawer.spans.length > 0
              ? "Highlight the words this score is based on"
              : "No evidence spans on this dimension"
          }
        >
          {title}
          {drawer.spans.length > 0 && (
            <span className="provenance ml-1.5" data-numeric>
              {drawer.spans.length} quote{drawer.spans.length === 1 ? "" : "s"}
            </span>
          )}
        </button>

        <div className="flex shrink-0 items-center gap-1.5">
          {rubricDimension?.concept_bearing && (
            <Pill
              tone="brand"
              title="This part of the marking is what moves your skill graph. The others don't."
            >
              moves your skill graph
            </Pill>
          )}
          <AgreementBadge agreement={drawer.agreement} spread={spread} />
        </div>
      </header>

      {/* ── the gate ───────────────────────────────────────────────────── */}
      {displayable ? (
        <p className="mt-2 text-title font-semibold text-ink" data-numeric>
          {drawer.calibrated_score?.toFixed(1)}
          <span className="ml-1 text-sm font-normal text-ink-faint">out of 4</span>
        </p>
      ) : (
        <p className="mt-2 rounded border-l-2 border-line-strong bg-surface-sunken px-2.5 py-1.5 text-xs text-ink-soft">
          {GATE_NOTE}
        </p>
      )}

      {drawer.reasoning && <p className="mt-2.5 text-sm text-ink">{drawer.reasoning}</p>}

      {/* Bare ids (kp_2) mean nothing to a student; the notes have the
          wording. Shown when the entry carries its own text, or in dev mode. */}
      {visibleMissing(drawer.missing_key_points, devMode).length > 0 && (
        <div className="mt-3">
          <p className="rule-label">Not covered</p>
          <ul className="mt-1 space-y-0.5">
            {visibleMissing(drawer.missing_key_points, devMode).map((point) => (
              <li key={point} className="flex gap-2 text-sm text-ink-soft">
                <span aria-hidden className="text-ink-faint">
                  ○
                </span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {score && score.disqualifiers_triggered.length > 0 && (
        <p className="mt-3 rounded border border-contested-line bg-contested-soft px-2.5 py-1.5 text-xs text-ink">
          <strong className="font-semibold">Flagged for a human to look at:</strong>{" "}
          {score.disqualifiers_triggered.join(", ")}. This does not reduce the score — a flag is
          a flag, not a deduction.
        </p>
      )}

      {rubricDimension && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowAnchors((open) => !open)}
            className="provenance hover:text-ink-soft"
            aria-expanded={showAnchors}
          >
            {showAnchors ? "▾" : "▸"} what each level looks like
          </button>
          {showAnchors && (
            <dl className="mt-1.5 space-y-1 border-l border-line pl-3">
              {Object.entries(rubricDimension.anchors)
                .sort(([a], [b]) => Number(b) - Number(a))
                .map(([level, text]) => (
                  <div key={level} className="text-xs">
                    <dt className="provenance inline" data-numeric>
                      {level}
                    </dt>
                    <dd className="ml-2 inline text-ink-soft">{text}</dd>
                  </div>
                ))}
            </dl>
          )}
        </div>
      )}

      {/* ── developer view ─────────────────────────────────────────────── */}
      {devMode && (
        <dl className="mt-3 border-t border-line pt-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <Figure label="raw" value={drawer.raw_score} />
            <Figure label="credited" value={drawer.credited_score} />
            <Figure
              label="calibrated"
              value={drawer.calibrated_score ?? "—"}
              title="null while the display gate is closed"
            />
            {spread !== undefined && <Figure label="spread" value={spread} />}
            {score && <Figure label="hint level" value={score.hint_level_used} />}
            {score && (
              <Figure
                label="model_confidence"
                value={score.model_confidence.toFixed(2)}
                title="Self-reported. Feeds ECE; never shown to a student (§8.1)."
              />
            )}
          </div>
        </dl>
      )}
    </Panel>
  );
}

function Figure({
  label,
  value,
  title,
}: {
  label: string;
  value: string | number;
  title?: string;
}) {
  return (
    <div title={title}>
      <dt className="rule-label">{label}</dt>
      <dd className="provenance text-ink" data-numeric>
        {value}
      </dd>
    </div>
  );
}

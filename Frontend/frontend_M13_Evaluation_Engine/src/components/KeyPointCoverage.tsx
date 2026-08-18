/**
 * What the answer covered, and what it missed.
 *
 * This is the most actionable thing on the page and it is not a score: a
 * student can do something about "you never said what happens on a collision"
 * in a way they cannot do anything about "3 out of 4".
 *
 * Two honesty constraints:
 *
 * - **The method travels with the numbers.** Entailment from an NLI model and
 *   lexical overlap are not the same measurement, and a checklist that looks
 *   identical either way invites comparison across a change that moved every
 *   value. `extractor_versions.key_point_coverage` says which ran.
 *
 * - **A scaffolded run is labelled.** When the coverage vector was shown to
 *   the evaluator, the score and the checklist are not independent readings,
 *   and the calibration fit stratifies on exactly this (§6.4).
 */

import type { ReactNode } from "react";

import { Panel, Pill, Section } from "../ui/primitives";

/** Above this, a key point counts as covered — `KP_ENTAILMENT_THRESHOLD`. */
const COVERED = 0.5;

export function KeyPointCoverage({
  coverage,
  scaffoldUsed,
  method,
}: {
  coverage: Record<string, number>;
  scaffoldUsed: boolean;
  method?: string;
}) {
  const points = Object.entries(coverage);
  if (points.length === 0) return null;

  const covered = points.filter(([, value]) => value >= COVERED).length;

  return (
    <Section
      label="What you covered"
      meta={
        <span data-numeric>
          {covered} of {points.length}
        </span>
      }
    >
      <Panel className="px-4 py-3">
        <ul className="space-y-1.5">
          {points.map(([point, value]) => (
            <li key={point} className="flex items-baseline gap-2.5 text-sm">
              <span
                aria-hidden
                className={value >= COVERED ? "text-confirmed" : "text-ink-faint"}
              >
                {value >= COVERED ? "●" : "○"}
              </span>
              <span className={value >= COVERED ? "text-ink" : "text-ink-soft"}>{point}</span>
              <span className="provenance ml-auto shrink-0" data-numeric title="entailment score">
                {value.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>

        <Footnote>
          {method && (
            <>
              Measured by <code className="font-mono">{method}</code>.{" "}
            </>
          )}
          {scaffoldUsed ? (
            <>
              <Pill tone="reported">scaffolded</Pill> This list was shown to the evaluator before
              it scored, so the checklist and the scores are not two independent readings of the
              same answer.
            </>
          ) : (
            <>The evaluator scored without seeing this list.</>
          )}
        </Footnote>
      </Panel>
    </Section>
  );
}

function Footnote({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">{children}</p>
  );
}

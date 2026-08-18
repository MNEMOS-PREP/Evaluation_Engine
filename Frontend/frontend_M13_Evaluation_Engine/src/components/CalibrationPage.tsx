/**
 * The display gate.
 *
 * The single most important screen for anyone asking what this module's
 * numbers mean, because today the answer is "there aren't any, and here is
 * exactly why". Every threshold is listed with its value, every fitted row
 * shows whether it passed, and a closed gate shows its reasons in the words
 * the backend produced — "the gate said no" is not an answer to a question a
 * student, a faculty reviewer and an examiner all ask.
 *
 * `display_numeric: false` is the normal state and is not a bug. It means no
 * mapping has been fitted for that (dimension, round_type, ensemble_config),
 * or one was fitted and did not clear the bar. Either way no number is shown
 * anywhere in the product for that dimension.
 */

import { useCalibration } from "../api";
import type { CalibrationThresholds } from "../types";
import { Empty, Panel, Pill, Section, SkeletonRows } from "../ui/primitives";

const THRESHOLD_NOTE: Record<keyof CalibrationThresholds, string> = {
  qwk_overall_min: "agreement with human raters across all dimensions",
  qwk_dimension_min: "agreement with human raters on this dimension alone",
  length_bias_max: "score levels per log-token — how much length alone moves a score",
  ece_max: "expected calibration error on the evaluator's own confidence",
  min_fit_n: "human-rated items required before a mapping is fitted at all",
};

export function CalibrationPage() {
  const calibration = useCalibration();

  if (calibration.isLoading) return <SkeletonRows rows={5} />;

  const thresholds = calibration.data?.thresholds;
  const fitted = calibration.data?.fitted ?? [];

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Calibration and the display gate</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          No dimension shows a number until its scores have been checked against human raters and
          cleared every threshold below. This is the mechanism, not a policy someone applies by
          hand — the evaluation pipeline reads this table and leaves{" "}
          <code className="font-mono">calibrated_score</code> null when it is not satisfied.
        </p>
      </header>

      <Section label="Thresholds" title="What has to be true">
        <Panel className="px-4 py-3">
          <table className="w-full text-left text-sm">
            <tbody>
              {thresholds &&
                (Object.keys(thresholds) as (keyof CalibrationThresholds)[]).map((key) => (
                  <tr key={key} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-4 font-mono text-xs text-ink">{key}</td>
                    <td className="py-1.5 pr-4 text-ink" data-numeric>
                      {thresholds[key]}
                    </td>
                    <td className="py-1.5 text-ink-soft">{THRESHOLD_NOTE[key]}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Panel>
      </Section>

      <Section label="Fitted mappings" meta={`${fitted.length} rows`}>
        {fitted.length === 0 ? (
          <Empty title="Nothing is calibrated yet">
            <p>
              So <code className="font-mono">display_numeric</code> is false everywhere, no
              dimension renders a number, and the overall score is null on every evaluation. The
              reasoning and the evidence are real and shown; the numbers behind them are not
              claimed to be accurate, because nobody has checked them yet.
            </p>
            <p className="mt-2">
              What unblocks it is not code. It is ethics clearance, then rater recruitment, then
              roughly 2,400 human ratings — after which a mapping is fitted per dimension and this
              table fills in.
            </p>
          </Empty>
        ) : (
          <div className="space-y-2">
            {fitted.map((row) => (
              <Panel
                key={`${row.dimension_key}:${row.round_type}:${row.ensemble_config}`}
                className="px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium text-ink">
                    {row.dimension_key}
                    <span className="provenance ml-1.5">
                      {row.round_type} · {row.ensemble_config}
                    </span>
                  </p>
                  <Pill tone={row.display_numeric ? "confirmed" : "reported"}>
                    {row.display_numeric ? "shows a number" : "no number shown"}
                  </Pill>
                </div>

                <p className="provenance mt-1">
                  {row.method} · fitted on {row.n} · QWK {row.qwk.toFixed(2)}
                </p>

                {Object.keys(row.gate_reasons).length > 0 && (
                  <ul className="mt-2 space-y-0.5 border-t border-line pt-2">
                    {Object.entries(row.gate_reasons).map(([key, reason]) => (
                      <li key={key} className="text-xs text-ink-soft">
                        <span className="font-mono text-ink-faint">{key}</span> — {reason}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            ))}
          </div>
        )}
      </Section>

      <Section label="Why it works this way">
        <Panel tone="sunken" className="px-4 py-3">
          <p className="text-sm text-ink-soft">
            A confidently fabricated "7.5 out of 10" is worse than no score at all. It teaches
            students the wrong things about their own answers, and no placement cell will rely on
            a number whose accuracy nobody measured. Showing the reasoning without the number is
            not a degraded experience — it is the honest one until the measurement exists.
          </p>
        </Panel>
      </Section>
    </>
  );
}

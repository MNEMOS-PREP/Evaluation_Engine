/**
 * One scored turn — the module's main screen.
 *
 * Layout is the argument. The answer takes the left two-thirds at reading
 * size; the judgements sit in the margin. Selecting a judgement lights its
 * quotes in the text, and clicking a quote selects the judgement — so "why
 * this score" is answered by looking, not by reading a justification that
 * claims to be about words you have to take on faith.
 *
 * The composite is deliberately absent most of the time. `composite` is null
 * whenever ANY contributing dimension is display-suppressed, because a
 * composite computed over whichever subset happens to be calibrated is a
 * different measurement each week (§6.4 step 7).
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useEvaluation, useEvidence, useRubric } from "../api";
import type { TurnEvaluation } from "../types";
import { useDevMode } from "../ui/AppShell";
import { Btn, Empty, Field, Panel, Pill, Rows, Section, SkeletonRows } from "../ui/primitives";
import { DeliverySection } from "./DeliverySection";
import { DisputeDialog } from "./DisputeDialog";
import { Judgement } from "./Judgement";
import { KeyPointCoverage } from "./KeyPointCoverage";
import { Transcript } from "./Transcript";

export function TurnPage() {
  const { turnId } = useParams<{ turnId: string }>();
  const devMode = useDevMode();
  const [active, setActive] = useState<string | null>(null);
  const [disputing, setDisputing] = useState(false);

  const evaluation = useEvaluation(turnId);
  const evidence = useEvidence(turnId);
  // The drawer resolves the rubric for us. `TurnEvaluation` carries only an
  // opaque `rubric_id`, so without this the dimension names and the anchors —
  // "what does level 3 mean" — would be unfetchable from a stored evaluation.
  const rubric = useRubric(evidence.data?.round_type);

  if (evaluation.isLoading || evidence.isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (evaluation.isError || !evaluation.data || !evidence.data) {
    return (
      <Empty title="No evaluation for that turn">
        <p>
          Nothing has been scored under this id yet. Score an answer and this page fills in.
        </p>
        <p className="provenance mt-2">{turnId}</p>
        <div className="mt-4">
          <Link to="/score">
            <Btn variant="primary">Score an answer</Btn>
          </Link>
        </div>
      </Empty>
    );
  }

  const evalData = evaluation.data;
  const drawer = evidence.data;
  const transcript =
    drawer.artifacts.find((a) => a.artifact_type === "transcript") ?? drawer.artifacts[0];
  const dimensionsByKey = new Map(
    (rubric.data?.dimensions ?? []).map((dimension) => [dimension.key, dimension]),
  );

  return (
    <>
      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-title font-semibold text-ink">Your answer, and what it earned</h1>
          <StatusPill evaluation={evalData} />
          {evalData.adjudicated && (
            <Pill tone="reported" title={evalData.adjudication_note ?? undefined}>
              adjudicated
            </Pill>
          )}
          {evalData.superseded_by && (
            <Pill tone="contested" title="A newer evaluation replaces this one.">
              superseded
            </Pill>
          )}
        </div>
        <p className="provenance mt-1">
          turn {evalData.turn_id} · {evalData.ensemble_config} ·{" "}
          {evalData.evaluated_at ? new Date(evalData.evaluated_at).toLocaleString() : "—"}
        </p>
      </header>

      <GradeBanner evaluation={evalData} />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        {/* ---------- the answer ---------- */}
        <div className="min-w-0">
          <Section
            label="What you said"
            meta={
              transcript ? (
                <span title="Checked at read time against the checksum recorded when this answer was scored.">
                  {transcript.intact ? "checksum verified" : "checksum MISMATCH"}
                </span>
              ) : undefined
            }
          >
            {transcript ? (
              <Transcript
                artifact={transcript}
                dimensions={drawer.dimensions}
                activeDimension={active}
                onSelectDimension={setActive}
              />
            ) : (
              <Empty title="The text of this answer is not stored">
                <p>
                  This evaluation predates artifact storage, so the quotes are listed below
                  without the surrounding answer.
                </p>
              </Empty>
            )}

            {active && (
              <p className="mt-3 text-xs text-ink-soft">
                Showing the quotes behind <strong className="text-ink">{active}</strong>.{" "}
                <button
                  type="button"
                  onClick={() => setActive(null)}
                  className="text-brand hover:underline"
                >
                  show all
                </button>
              </p>
            )}
          </Section>

          {drawer.artifacts
            .filter((artifact) => artifact !== transcript)
            .map((artifact) => (
              <Section key={artifact.artifact_id} label={artifact.artifact_type}>
                <Panel tone="sunken" className="overflow-x-auto p-3">
                  <pre className="font-mono text-xs text-ink">{artifact.text}</pre>
                </Panel>
              </Section>
            ))}

          <KeyPointCoverage
            coverage={evalData.key_point_coverage}
            scaffoldUsed={evalData.scaffold_used}
            method={evalData.versions.extractor_versions?.key_point_coverage}
          />

          <DeliverySection delivery={evalData.delivery} />
        </div>

        {/* ---------- the margin ---------- */}
        <div className="min-w-0">
          <Section
            label="How it was judged"
            meta={`${drawer.dimensions.length} dimension${drawer.dimensions.length === 1 ? "" : "s"}`}
          >
            <div className="space-y-2.5">
              {drawer.dimensions.map((dimension) => (
                <Judgement
                  key={dimension.dimension_key}
                  drawer={dimension}
                  score={evalData.aggregated.find(
                    (s) => s.dimension_key === dimension.dimension_key,
                  )}
                  rubricDimension={dimensionsByKey.get(dimension.dimension_key)}
                  spread={evalData.spread_levels[dimension.dimension_key]}
                  devMode={devMode}
                  active={active === dimension.dimension_key}
                  onToggle={() =>
                    setActive(active === dimension.dimension_key ? null : dimension.dimension_key)
                  }
                />
              ))}
            </div>

            <CompositeNote evaluation={evalData} />

            <div className="mt-4 flex flex-wrap gap-2">
              <Btn variant="secondary" size="sm" onClick={() => setDisputing(true)}>
                This looks wrong
              </Btn>
              <Link to={`/turns/${evalData.turn_id}/outbound`}>
                <Btn variant="ghost" size="sm">
                  What other modules receive
                </Btn>
              </Link>
            </div>
          </Section>

          {devMode && <DeveloperPanel evaluation={evalData} />}
        </div>
      </div>

      {disputing && (
        <DisputeDialog
          evaluationId={evalData.id}
          dimensions={drawer.dimensions.map((d) => d.dimension_key)}
          onClose={() => setDisputing(false)}
        />
      )}
    </>
  );
}

function StatusPill({ evaluation }: { evaluation: TurnEvaluation }) {
  if (evaluation.status === "complete") return null;
  const tone = evaluation.status === "failed" ? "contested" : "reported";
  const words =
    evaluation.status === "failed"
      ? "could not be scored"
      : "waiting for a human to look at it";
  return <Pill tone={tone}>{words}</Pill>;
}

/**
 * What these scores are FIT FOR (§11).
 *
 * A free-tier evaluation is a real evaluation with real verified evidence. It
 * is simply not eligible to be displayed as a number or to enter the
 * calibration corpus — and saying so is more useful than hiding it, because
 * "why does this look different from the paper" is otherwise unanswerable.
 */
function GradeBanner({ evaluation }: { evaluation: TurnEvaluation }) {
  if (evaluation.score_grade === "calibration") return null;
  return (
    <p className="mb-8 rounded-panel border border-line bg-surface-sunken px-3.5 py-2.5 text-xs text-ink-soft">
      <strong className="font-semibold text-ink">Development-grade evaluation.</strong> The
      reasoning and the quotes below are real, and every quote was checked against the answer.
      The scores behind them are not eligible to be shown as a number or to enter the
      calibration corpus — that is what <code className="font-mono">score_grade: dev</code>{" "}
      means, and it is enforced by the field rather than by anyone remembering.
    </p>
  );
}

function CompositeNote({ evaluation }: { evaluation: TurnEvaluation }) {
  if (evaluation.composite !== null) {
    return (
      <p className="mt-4 text-sm text-ink">
        Overall{" "}
        <strong className="text-title font-semibold" data-numeric>
          {evaluation.composite.toFixed(1)}
        </strong>
      </p>
    );
  }
  return (
    <p className="mt-4 rounded border-l-2 border-line-strong bg-surface-sunken px-2.5 py-1.5 text-xs text-ink-soft">
      There is no overall score, on purpose. One is only computed when every dimension above has
      passed the accuracy check — averaging whichever ones happen to have passed would give a
      different measurement each week and call it the same name.
    </p>
  );
}

function DeveloperPanel({ evaluation }: { evaluation: TurnEvaluation }) {
  const totals = evaluation.evaluators.reduce(
    (acc, e) => ({
      tokens_in: acc.tokens_in + e.tokens.tokens_in,
      tokens_out: acc.tokens_out + e.tokens.tokens_out,
      cached_in: acc.cached_in + e.tokens.cached_in,
      cost_inr: acc.cost_inr + e.tokens.cost_inr,
    }),
    { tokens_in: 0, tokens_out: 0, cached_in: 0, cost_inr: 0 },
  );
  const cacheRatio =
    totals.tokens_in + totals.cached_in > 0
      ? totals.cached_in / (totals.tokens_in + totals.cached_in)
      : 0;

  return (
    <Section label="Developer" title="The run">
      <Panel className="px-4 py-3">
        <Rows>
          <Field label="evaluation id">{evaluation.id}</Field>
          <Field label="ensemble">{evaluation.ensemble_config}</Field>
          <Field label="score grade">{evaluation.score_grade}</Field>
          <Field label="scaffold used">{String(evaluation.scaffold_used)}</Field>
          <Field label="consent id">{evaluation.consent_id ?? "none — observations withheld"}</Field>
          <Field label="tokens in / out">
            {totals.tokens_in} / {totals.tokens_out}
          </Field>
          <Field label="cache read ratio">
            {/* Master plan §47.1 treats < 0.5 as a bug. */}
            <span className={cacheRatio < 0.5 ? "text-contested" : undefined}>
              {(cacheRatio * 100).toFixed(0)}%
            </span>
          </Field>
          <Field label="cost">₹{totals.cost_inr.toFixed(3)}</Field>
        </Rows>
      </Panel>

      <Panel className="mt-3 px-4 py-3">
        <p className="rule-label mb-2">Members</p>
        <table className="w-full text-left">
          <thead>
            <tr className="provenance">
              <th className="pb-1 pr-2 font-normal">#</th>
              <th className="pb-1 pr-2 font-normal">model</th>
              <th className="pb-1 pr-2 font-normal">seed</th>
              <th className="pb-1 pr-2 font-normal">ms</th>
              <th className="pb-1 font-normal">state</th>
            </tr>
          </thead>
          <tbody>
            {evaluation.evaluators.map((member) => (
              <tr key={member.evaluator_index} className="border-t border-line">
                <td className="provenance py-1 pr-2">{member.evaluator_index}</td>
                <td className="provenance py-1 pr-2 break-all">{member.model_id}</td>
                <td className="provenance py-1 pr-2">{member.dimension_order_seed}</td>
                <td className="provenance py-1 pr-2">{member.latency_ms}</td>
                <td className="py-1">
                  {member.dropped_reason ? (
                    <Pill tone="contested" title={member.dropped_reason}>
                      dropped
                    </Pill>
                  ) : (
                    <Pill tone="confirmed">voted</Pill>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="provenance mt-2">
          A dropped member does not vote. Seeds differ because two identical calls to one model
          are one sample twice.
        </p>
      </Panel>

      <Panel className="mt-3 px-4 py-3">
        <p className="rule-label mb-2">Versions</p>
        <Rows>
          {Object.entries(evaluation.versions).map(([key, value]) => (
            <Field key={key} label={key}>
              {value === null || value === undefined
                ? "—"
                : typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)}
            </Field>
          ))}
        </Rows>
      </Panel>
    </Section>
  );
}

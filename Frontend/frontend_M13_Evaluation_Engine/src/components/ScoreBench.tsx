/**
 * Score an answer.
 *
 * In production M06 posts a turn when it finishes and a student never sees
 * this screen. Standalone, it is the way in: M05 is absent, so the question
 * comes from the committed fixture bank (§6.11), and the "clone and run"
 * promise is only real if there is something to click after the clone.
 *
 * The regression cases are on the same page on purpose. Each carries a
 * human-set expected band and a `band_source`, and loading one shows what the
 * suite asserts — which makes the honest failure visible rather than
 * something you find in CI. A band is never derived from model output;
 * snapshotting today's score as tomorrow's ground truth freezes today's bias
 * (Trap 9), and a gate in the backend suite asserts no `band_source` is
 * `model`.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useDeps, useEnsembles, useEvaluate, useFixtures } from "../api";
import { Btn, Empty, Panel, Pill, Section, Select, SkeletonRows, TextArea } from "../ui/primitives";

export function ScoreBench() {
  const navigate = useNavigate();
  const fixtures = useFixtures();
  const ensembles = useEnsembles();
  const deps = useDeps();
  const evaluate = useEvaluate();

  const [questionLabel, setQuestionLabel] = useState("");
  const [answer, setAnswer] = useState("");
  const [hintLevel, setHintLevel] = useState(0);
  const [ensemble, setEnsemble] = useState("");

  const questions = fixtures.data?.questions ?? [];
  // The backend owns this list and 422s on a name it does not know, so it is
  // fetched rather than copied — and the default comes from there too.
  const activeEnsemble = ensemble || ensembles.data?.default || "";
  const activeLabel = questionLabel || questions[0]?.label || "";
  const cases = (fixtures.data?.regression_cases ?? []).filter(
    (regression) => regression.question === activeLabel,
  );
  const scoringOff = deps.data ? !deps.data.evaluation_available : false;

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Score an answer</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          Pick one of the sample questions, paste an answer, and see how the scorer marks it and
          why. The samples are a fixed practice set, kept apart from the questions students are
          asked.
        </p>
      </header>

      {scoringOff && (
        <Panel className="mb-8 border-reported-line bg-reported-soft px-4 py-3">
          <p className="text-sm text-ink">
            <strong className="font-semibold">Scoring is switched off.</strong> No API key is
            configured, so there is no evaluator to call. Everything else on this site works —
            rubrics, stored evaluations, the outbox and the contract inspector all read from what
            is already there. The module reports this rather than returning a fabricated number.
          </p>
        </Panel>
      )}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <Section label="The turn">
            {fixtures.isLoading ? (
              <SkeletonRows rows={4} />
            ) : questions.length === 0 ? (
              <Empty title="No question bank">
                <p>Neither M05 nor the fixture bank answered. Check /v1/fixtures.</p>
              </Empty>
            ) : (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  evaluate.mutate(
                    {
                      question_label: activeLabel,
                      answer_text: answer,
                      hint_level_used: hintLevel,
                      ensemble: activeEnsemble,
                    },
                    { onSuccess: (result) => navigate(`/turns/${result.turn_id}`) },
                  );
                }}
              >
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="sm:col-span-2">
                    <Select
                      label="Question"
                      value={activeLabel}
                      onChange={(event) => setQuestionLabel(event.target.value)}
                    >
                      {questions.map((question) => (
                        <option key={question.label} value={question.label}>
                          {question.label} · {question.round_type}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <Select
                    label="Ensemble"
                    value={activeEnsemble}
                    onChange={(event) => setEnsemble(event.target.value)}
                  >
                    {(ensembles.data?.ensembles ?? []).map((config) => (
                      <option key={config.name} value={config.name}>
                        {config.name} — {config.size}{" "}
                        {config.size === 1 ? "evaluator" : "members"}
                        {config.agreement_signal ? "" : ", no agreement signal"}
                      </option>
                    ))}
                  </Select>
                </div>

                <TextArea
                  label="Answer"
                  hint="Exactly what the candidate said. Every quote in the result will be an offset into this text."
                  rows={10}
                  required
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  placeholder="Paste or type an answer…"
                />

                <div className="flex flex-wrap items-end gap-4">
                  <div className="w-44">
                    <Select
                      label="Hints used"
                      value={String(hintLevel)}
                      onChange={(event) => setHintLevel(Number(event.target.value))}
                    >
                      {[0, 1, 2, 3].map((level) => (
                        <option key={level} value={level}>
                          {level === 0 ? "none" : `level ${level}`}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <p className="flex-1 text-xs text-ink-soft">
                    The credit factor for each level is published in the rubric, not hidden in the
                    scorer — and it is applied exactly once, here, so the skill graph does not
                    deduct it again.
                  </p>
                  <Btn
                    type="submit"
                    variant="primary"
                    disabled={evaluate.isPending || !answer.trim()}
                  >
                    {evaluate.isPending ? "Scoring…" : "Score it"}
                  </Btn>
                </div>

                {evaluate.isError && (
                  <p role="alert" className="text-sm text-contested">
                    {(evaluate.error as Error).message}
                  </p>
                )}
              </form>
            )}
          </Section>
        </div>

        <div className="min-w-0">
          <Section
            label="Regression cases"
            meta={`${cases.length} for this question`}
          >
            {cases.length === 0 ? (
              <p className="text-sm text-ink-soft">None recorded for this question.</p>
            ) : (
              <div className="space-y-2">
                {cases.map((regression) => (
                  <Panel key={regression.label} className="px-3.5 py-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-sm font-medium text-ink">{regression.label}</p>
                      <span className="provenance" data-numeric>
                        expects {regression.expected_band[0]}–{regression.expected_band[1]}
                      </span>
                    </div>
                    {regression.note && (
                      <p className="mt-1 text-xs text-ink-soft">{regression.note}</p>
                    )}
                    <div className="mt-2">
                      <Pill
                        tone={regression.band_source === "model" ? "contested" : "neutral"}
                        title="Where the expected band came from. Never a model."
                      >
                        band from {regression.band_source}
                      </Pill>
                    </div>
                  </Panel>
                ))}
              </div>
            )}
            <p className="mt-3 text-xs text-ink-soft">
              Expected bands are set by a person and never by a model. Snapshotting today's output
              as the expected band would freeze today's bias as tomorrow's ground truth.
            </p>
          </Section>
        </div>
      </div>
    </>
  );
}

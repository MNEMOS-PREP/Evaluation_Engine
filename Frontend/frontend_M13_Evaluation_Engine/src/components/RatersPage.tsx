/**
 * The rater workbench — and the honest account of why it is not one yet.
 *
 * AC-13.15 requires that audio and transcripts are **de-identified before they
 * reach a peer rater**. That is not built. The backend knows it: the queue
 * endpoint returns turn ids and a note saying so, deliberately, rather than
 * returning content it cannot yet strip.
 *
 * So this screen does not open an answer. Building a rating form that shows a
 * classmate's un-de-identified transcript would satisfy the endpoint and break
 * the acceptance criterion, and the acceptance criterion is the one protecting
 * a real person. The queue is shown, the gap is stated, and the submission
 * form exists for a pilot where the material reached the rater through a
 * channel that did de-identify it.
 *
 * All three MFRM facets — candidate, item, rater — are required on submission,
 * because a rater-severity model cannot be fitted from a rating that does not
 * say who rated what.
 */

import { useState } from "react";

import { useRaterQueue, useSubmitRating } from "../api";
import { Btn, Panel, Pill, Section, Select, SkeletonRows } from "../ui/primitives";

export function RatersPage() {
  const [raterId, setRaterId] = useState("");
  const [submitted, setSubmitted] = useState(raterId);
  const queue = useRaterQueue(submitted);
  const rating = useSubmitRating(submitted);

  const [form, setForm] = useState({
    turn_id: "",
    question_id: "",
    candidate_id: "",
    dimension_key: "",
    round_type: "dsa_verbal",
    rubric_version: "1.0.0",
    score: 2,
    time_spent_s: 0,
  });

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Rater workbench</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          The human ratings this module is calibrated against. Roughly 2,400 of them, across
          dimensions and round types, are what open the display gate.
        </p>
      </header>

      <Panel className="mb-8 border-contested-line bg-contested-soft px-4 py-3.5">
        <p className="text-sm text-ink">
          <strong className="font-semibold">This workbench cannot show you an answer yet.</strong>{" "}
          AC-13.15 requires audio and transcripts to be de-identified before a peer rater sees
          them, and that step is not built. Rather than ship a screen that shows a classmate's
          transcript with their name still in it, the queue below lists ids only — which is what
          the API returns, on purpose.
        </p>
        <p className="mt-2 text-sm text-ink-soft">
          Two things gate the annotation study, and neither is code: an ethics annexe has to be
          filed and cleared, and raters have to be recruited and trained on the anchors. The
          de-identified rendering is the engineering half and belongs with them.
        </p>
      </Panel>

      <Section label="Queue" title="Turns you have not rated">
        <form
          className="mb-4 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmitted(raterId);
          }}
        >
          <label className="min-w-56 flex-1">
            <span className="rule-label">Rater id</span>
            <input
              value={raterId}
              onChange={(event) => setRaterId(event.target.value)}
              placeholder="your rater id"
              className="mt-1.5 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-brand-line"
            />
          </label>
          <Btn type="submit" variant="secondary">
            Load queue
          </Btn>
        </form>

        {queue.isLoading && <SkeletonRows rows={3} />}

        {queue.data && (
          <Panel className="px-4 py-3">
            <p className="text-sm text-ink">
              <span data-numeric className="font-semibold">
                {queue.data.remaining}
              </span>{" "}
              waiting for {queue.data.rater_id}
            </p>
            <ul className="mt-2 space-y-1">
              {queue.data.items.map((item) => (
                <li
                  key={item.turn_id}
                  className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-1.5"
                >
                  <span className="provenance">{item.turn_id}</span>
                  <div className="flex items-center gap-2">
                    <Pill tone="neutral">{item.round_type}</Pill>
                    <Btn
                      size="sm"
                      variant="ghost"
                      disabled
                      title="Blocked by AC-13.15 — de-identified rendering is not built."
                    >
                      open
                    </Btn>
                  </div>
                </li>
              ))}
            </ul>
            <p className="provenance mt-2">{queue.data.note}</p>
          </Panel>
        )}
      </Section>

      <Section
        label="Pilot entry"
        title="Record a rating"
        meta="all three MFRM facets required"
      >
        <Panel className="px-4 py-3.5">
          <p className="mb-3 text-xs text-ink-soft">
            For a pilot where the rater received de-identified material through another channel.
            Every field below is required by the facet model: a rating that does not say which
            rater judged which candidate on which item cannot contribute to a severity estimate,
            and averaging it in anyway is how a harsh rater becomes a weak candidate.
          </p>

          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              rating.mutate({ ...form, rater_id: submitted });
            }}
          >
            {(
              [
                ["turn_id", "Turn id"],
                ["question_id", "Question id"],
                ["candidate_id", "Candidate id"],
                ["dimension_key", "Dimension"],
                ["round_type", "Round type"],
                ["rubric_version", "Rubric version"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block">
                <span className="rule-label">{label}</span>
                <input
                  required
                  value={form[key]}
                  onChange={(event) => setForm({ ...form, [key]: event.target.value })}
                  className="mt-1.5 w-full rounded-md border border-line bg-surface px-3 py-1.5 font-mono text-xs text-ink outline-none focus:border-brand-line"
                />
              </label>
            ))}

            <Select
              label="Score"
              value={String(form.score)}
              onChange={(event) => setForm({ ...form, score: Number(event.target.value) })}
            >
              {[0, 1, 2, 3, 4].map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </Select>

            <div className="flex items-end">
              <Btn
                type="submit"
                variant="primary"
                disabled={!submitted || rating.isPending}
                title={submitted ? undefined : "Load a queue first so the rating has a rater id"}
              >
                {rating.isPending ? "Saving…" : "Record rating"}
              </Btn>
            </div>
          </form>

          {rating.isSuccess && (
            <p className="mt-3 text-xs text-confirmed">Recorded as {rating.data.id}.</p>
          )}
          {rating.isError && (
            <p role="alert" className="mt-3 text-xs text-contested">
              {(rating.error as Error).message}
            </p>
          )}
        </Panel>
      </Section>
    </>
  );
}

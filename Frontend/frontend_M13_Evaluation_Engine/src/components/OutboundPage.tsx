/**
 * What one evaluation owes M04, M02 and M19.
 *
 * A developer surface, and the most useful one in the repo right now: it shows
 * real shapes, real ids and real evidence for a sibling module that has not
 * been built yet, which is the difference between a merge and a debugging
 * session. `CONTRACTS.md` is the prose; this is the same thing with data in it.
 *
 * The routing rule is the part worth looking at. Exactly one dimension is
 * concept-bearing and only that one reaches technical concepts; a
 * communication dimension reaches communication concepts; everything else
 * produces no observation at all. Get it wrong and communication quality ends
 * up inside θ where nobody can untangle it later.
 */

import { Link, useParams } from "react-router-dom";

import { useOutbound } from "../api";
import { Btn, Empty, Field, Panel, Pill, Rows, Section, SkeletonRows } from "../ui/primitives";

export function OutboundPage() {
  const { turnId } = useParams<{ turnId: string }>();
  const outbound = useOutbound(turnId);

  if (outbound.isLoading) return <SkeletonRows rows={6} />;

  if (outbound.isError || !outbound.data) {
    return (
      <Empty title="Nothing to show for that turn">
        <p>
          Either it has not been scored, or its question package can no longer be resolved — the
          backend answers 409 rather than inventing one.
        </p>
        <p className="provenance mt-2">{(outbound.error as Error | null)?.message}</p>
      </Empty>
    );
  }

  const data = outbound.data;

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">What other modules receive</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          Everything below is queued through an outbox in the same transaction as the evaluation.
          If one of these modules is down, a mastery update is delayed — a student's score is not
          lost and their evaluation does not fail.
        </p>
        <p className="provenance mt-1">turn {turnId}</p>
      </header>

      <div className="mb-4">
        <Link to={`/turns/${turnId}`}>
          <Btn variant="ghost" size="sm">
            ← back to the evaluation
          </Btn>
        </Link>
      </div>

      {data.skipped && (
        <Panel className="mb-8 border-contested-line bg-contested-soft px-4 py-3">
          <p className="text-sm text-ink">
            <strong className="font-semibold">No observations were emitted.</strong>{" "}
            {data.skipped}
          </p>
        </Panel>
      )}

      <Section
        label="M04 · Skill Graph & Memory"
        title="Observations"
        meta={data.m04_url}
      >
        {data.m04_observations.length === 0 ? (
          <p className="text-sm text-ink-soft">None — see above.</p>
        ) : (
          <div className="space-y-3">
            {data.m04_observations.map((observation, i) => (
              // An observation not yet sent has no id (null from the API),
              // and a null key warned on every render of this page.
              <Panel
                key={observation.id ?? `${observation.concept_id}:${observation.source_dimension_key}:${i}`}
                className="px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium text-ink">{observation.concept_id}</p>
                  <div className="flex items-center gap-1.5">
                    <Pill tone="brand">from {observation.source_dimension_key}</Pill>
                    {observation.item === null && (
                      <Pill
                        tone="reported"
                        title="No calibrated item, so this observation updates counts and evidence and leaves the ability estimate alone."
                      >
                        not θ-eligible
                      </Pill>
                    )}
                  </div>
                </div>
                <Rows>
                  <Field label="id (uuid5, M04's own formula)">{observation.id}</Field>
                  <Field label="raw_category / n_categories">
                    {observation.raw_category} / {observation.n_categories}
                  </Field>
                  <Field label="outcome (display + BKT only)">{observation.outcome}</Field>
                  <Field label="response_model">{observation.response_model}</Field>
                  <Field label="weight">{observation.weight}</Field>
                  <Field label="evidence refs">{observation.evidence.length}</Field>
                  <Field label="consent_id">{observation.consent_id ?? "—"}</Field>
                </Rows>
              </Panel>
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-ink-soft">
          <code className="font-mono">raw_category</code> is the GRM likelihood input;{" "}
          <code className="font-mono">outcome</code> is the normalised 0–1 for display and BKT and
          is explicitly not the likelihood. The id is a content hash M04 derives too, so replaying
          a send is an insert conflict there rather than a second answer.
        </p>
      </Section>

      <Section label="M02 · JD Parser & Coverage Planner" title="Coverage transition">
        {data.m02_coverage ? (
          <Panel className="px-4 py-3">
            <Rows>
              {Object.entries(data.m02_coverage).map(([key, value]) => (
                <Field key={key} label={key}>
                  {String(value)}
                </Field>
              ))}
            </Rows>
            <p className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">
              <code className="font-mono">score</code> is the concept-bearing dimension. A
              requirement is covered by whether the candidate could do the thing, not by how well
              they narrated it.
            </p>
          </Panel>
        ) : (
          <p className="text-sm text-ink-soft">None.</p>
        )}
      </Section>

      <Section
        label="M19 · Reports & Evidence Ledger"
        title="Ledger entries"
        meta={`${data.m19_ledger.length} entries`}
      >
        <div className="space-y-2">
          {data.m19_ledger.map((entry) => (
            <Panel key={`${entry.claim_kind}:${entry.claim_key}`} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-ink">
                  {entry.claim_kind} · {entry.claim_key}
                </p>
                <span className="provenance" data-numeric>
                  {entry.value}
                </span>
              </div>
              <p className="provenance mt-1">
                {entry.evidence.length} evidence ref{entry.evidence.length === 1 ? "" : "s"} ·{" "}
                {entry.computed_at}
              </p>
            </Panel>
          ))}
        </div>
        <p className="mt-3 text-xs text-ink-soft">
          Append-only. A re-score inserts new entries and the old ones stay, which is what makes
          "re-scored under rubric v2.1" something the product can say out loud. Whether M19 may
          render any of these as a number is not M19's call — it reads the display gate.
        </p>
      </Section>
    </>
  );
}

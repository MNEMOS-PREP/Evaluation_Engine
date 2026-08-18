/**
 * The dispute queue — a reviewer's screen.
 *
 * Resolving a dispute appends; it never overwrites. Upholding one does not
 * silently rewrite the original score either: the correction is a new
 * evaluation that supersedes the old, and the old row stays readable, which is
 * what lets the product explain a changed number instead of pretending it was
 * always that.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { useDisputeQueue, useResolveDispute } from "../api";
import { Btn, Empty, Panel, Section, SkeletonRows, TextArea } from "../ui/primitives";

export function DisputesPage() {
  const queue = useDisputeQueue();
  const resolve = useResolveDispute();
  const [openId, setOpenId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [resolvedBy, setResolvedBy] = useState("");

  if (queue.isLoading) return <SkeletonRows rows={4} />;

  const disputes = queue.data?.disputes ?? [];

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Disputes</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          Every student who filed one was promised a human within two days, and a fresh question
          on the topic either way. The second half of that promise is already scheduled — M04 owns
          the re-test row — so this queue is only about the first.
        </p>
      </header>

      {disputes.length === 0 ? (
        <Empty title="Nothing waiting">
          <p>No open disputes.</p>
        </Empty>
      ) : (
        <Section label="Open" meta={`${queue.data?.open ?? 0}`}>
          <div className="space-y-2">
            {disputes.map((dispute) => (
              <Panel key={dispute.id} className="px-4 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink">
                      {dispute.reason.replace(/_/g, " ")}
                      {dispute.dimension_key && (
                        <span className="provenance ml-1.5">on {dispute.dimension_key}</span>
                      )}
                    </p>
                    {dispute.note && (
                      <p className="mt-1 text-sm text-ink-soft">“{dispute.note}”</p>
                    )}
                  </div>
                  <span className="provenance shrink-0">
                    {new Date(dispute.created_at).toLocaleString()}
                  </span>
                </div>

                <p className="provenance mt-1">evaluation {dispute.evaluation_id}</p>

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {/* Keyed on the TURN, not the evaluation: a re-score
                      supersedes the evaluation, and a reviewer wants the
                      answer as it stands rather than the reading that was
                      challenged. */}
                  {dispute.turn_id ? (
                    <Link to={`/turns/${dispute.turn_id}`}>
                      <Btn variant="ghost" size="sm">
                        open the answer
                      </Btn>
                    </Link>
                  ) : (
                    <Btn variant="ghost" size="sm" disabled title="The evaluation is no longer stored.">
                      answer unavailable
                    </Btn>
                  )}
                  <Btn
                    variant="secondary"
                    size="sm"
                    onClick={() => setOpenId(openId === dispute.id ? null : dispute.id)}
                  >
                    resolve
                  </Btn>
                </div>

                {openId === dispute.id && (
                  <div className="mt-3 space-y-3 border-t border-line pt-3">
                    <TextArea
                      label="What you found"
                      hint="Recorded with the resolution. The student sees it."
                      rows={3}
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                    <label className="block">
                      <span className="rule-label">Your name</span>
                      <input
                        value={resolvedBy}
                        onChange={(event) => setResolvedBy(event.target.value)}
                        className="mt-1.5 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-brand-line"
                        placeholder="who reviewed this"
                      />
                    </label>
                    <div className="flex flex-wrap gap-2">
                      <Btn
                        variant="primary"
                        size="sm"
                        disabled={resolve.isPending}
                        onClick={() =>
                          resolve.mutate(
                            {
                              disputeId: dispute.id,
                              upheld: true,
                              note,
                              resolvedBy: resolvedBy || "unknown",
                            },
                            { onSuccess: () => setOpenId(null) },
                          )
                        }
                      >
                        Uphold — the score was wrong
                      </Btn>
                      <Btn
                        variant="secondary"
                        size="sm"
                        disabled={resolve.isPending}
                        onClick={() =>
                          resolve.mutate(
                            {
                              disputeId: dispute.id,
                              upheld: false,
                              note,
                              resolvedBy: resolvedBy || "unknown",
                            },
                            { onSuccess: () => setOpenId(null) },
                          )
                        }
                      >
                        Reject — the score stands
                      </Btn>
                    </div>
                    <p className="text-xs text-ink-soft">
                      Upholding records the correction. It does not edit the original evaluation:
                      a re-score appends a new one and points the old at it, so the change itself
                      stays explainable.
                    </p>
                  </div>
                )}
              </Panel>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}

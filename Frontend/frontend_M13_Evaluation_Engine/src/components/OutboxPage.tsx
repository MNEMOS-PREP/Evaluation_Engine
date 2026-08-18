/**
 * The outbox.
 *
 * The rule this module cannot break, made visible: M13 never blocks on you,
 * and you never block on M13. Observations are written in the same transaction
 * as the evaluation and drained afterwards, so M04 being down delays a mastery
 * update rather than failing a student's score.
 *
 * The failures are shown rather than hidden. A row sitting here with an error
 * on it is the system working — the alternative is an evaluation that 500ed
 * because someone else's service was restarting.
 */

import { useDrainOutbox, useOutbox } from "../api";
import { Btn, Empty, Panel, Pill, Section, SkeletonRows } from "../ui/primitives";

export function OutboxPage() {
  const outbox = useOutbox();
  const drain = useDrainOutbox();

  if (outbox.isLoading) return <SkeletonRows rows={4} />;

  const data = outbox.data;

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Outbox</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          Observations bound for M04, held here until it acknowledges them. The id on each row is
          a content hash M04 derives too, so draining twice is an insert conflict there rather
          than a double-counted answer — which is what makes the retry safe.
        </p>
      </header>

      <Section
        label="Destination"
        action={
          <Btn
            variant="primary"
            size="sm"
            disabled={drain.isPending || !data?.pending}
            onClick={() => drain.mutate()}
          >
            {drain.isPending ? "Draining…" : "Drain now"}
          </Btn>
        }
      >
        <Panel className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span className="provenance">{data?.url}</span>
            <Pill tone={data?.authenticated ? "confirmed" : "reported"}>
              {data?.authenticated ? "service secret set" : "no service secret"}
            </Pill>
            <span className="ml-auto text-ink" data-numeric>
              <strong className="font-semibold">{data?.pending ?? 0}</strong> pending
            </span>
          </div>

          {drain.data && (
            <p className="mt-3 border-t border-line pt-2 text-sm text-ink-soft" data-numeric>
              Sent {drain.data.sent}, failed {drain.data.failed}, {drain.data.pending} still
              pending.
            </p>
          )}
        </Panel>
      </Section>

      <Section label="Pending" meta={data ? `showing up to 20` : undefined}>
        {!data || data.items.length === 0 ? (
          <Empty title="Nothing queued">
            <p>Every observation this module has produced has been acknowledged by M04.</p>
          </Empty>
        ) : (
          <Panel className="px-4 py-3">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="provenance">
                  <th className="pb-1 pr-3 font-normal">observation</th>
                  <th className="pb-1 pr-3 font-normal">concept</th>
                  <th className="pb-1 pr-3 font-normal">tries</th>
                  <th className="pb-1 font-normal">last error</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id} className="border-t border-line align-top">
                    <td className="provenance py-1.5 pr-3 break-all">{item.id}</td>
                    <td className="py-1.5 pr-3 text-ink">{item.concept_id}</td>
                    <td className="py-1.5 pr-3 text-ink" data-numeric>
                      {item.attempts}
                    </td>
                    <td className="py-1.5 text-xs text-ink-soft">{item.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>
    </>
  );
}

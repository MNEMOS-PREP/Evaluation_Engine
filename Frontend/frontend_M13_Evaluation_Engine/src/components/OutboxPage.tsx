/**
 * The outbox.
 *
 * The rule this module cannot break, made visible: M13 never blocks on you,
 * and you never block on M13. What a score owes other modules is written in
 * the same transaction as the evaluation and delivered afterwards by a worker,
 * so M04 being down delays a mastery update rather than failing a student's
 * score.
 *
 * The failures are shown rather than hidden. Until 2026-09-23 that sentence
 * was not true: this page listed pending rows only, and a row M04 had rejected
 * dropped off it — `0 pending`, "Nothing queued" — with the reason readable
 * only in the database. Stuck rows are listed now, per destination, with why.
 */

import { useDrainOutbox, useOutbox, useRequeueOutbox } from "../api";
import type { ChannelSummary } from "../types";
import { Btn, Empty, Panel, Pill, Section, SkeletonRows } from "../ui/primitives";

/** What each destination is, in words a reader of this page can act on. */
const DESTINATIONS: Record<string, { title: string; what: string }> = {
  "m04.observations": {
    title: "M04 — skill graph",
    what:
      "One observation per concept a scored answer bears on. The id is a content hash M04 " +
      "derives too, so a resend is an insert conflict there rather than a double-counted answer.",
  },
  "m02.coverage": {
    title: "M02 — coverage ledger",
    what:
      "The score for each turn, which M02 turns into a `scored` row for every requirement the " +
      "question touched. It may arrive before M06's `asked` row; M02 keeps it and applies it then.",
  },
};

function seconds(value: number | null): string {
  if (value === null) return "—";
  if (value < 90) return `${Math.round(value)} s`;
  if (value < 5400) return `${Math.round(value / 60)} min`;
  return `${(value / 3600).toFixed(1)} h`;
}

function Channel({ name, data }: { name: string; data: ChannelSummary }) {
  const meta = DESTINATIONS[name] ?? { title: name, what: "" };
  return (
    <Section
      label={meta.title}
      meta={data.configured === false ? "not configured" : `${data.sent} delivered`}
    >
      <Panel className="px-4 py-3">
        {meta.what && <p className="mb-3 max-w-2xl text-sm text-ink-soft">{meta.what}</p>}

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" data-numeric>
          <span className="text-ink">
            <strong className="font-semibold">{data.owed}</strong> owed
          </span>
          <span className="text-ink-soft">oldest waiting {seconds(data.oldest_owed_s)}</span>
          <span className="text-ink-soft">next retry in {seconds(data.next_retry_in_s)}</span>
          {data.stuck > 0 ? (
            <Pill tone="contested">{data.stuck} need a person</Pill>
          ) : (
            <Pill tone="confirmed">nothing stuck</Pill>
          )}
        </div>

        {data.errors.length > 0 && (
          <ul className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">
            {data.errors.map((e) => (
              <li key={e.error} className="py-0.5 break-all">
                <span className="text-ink" data-numeric>
                  {e.rows}×
                </span>{" "}
                {e.error}
              </li>
            ))}
          </ul>
        )}

        {data.stuck_rows.length > 0 && (
          <table className="mt-3 w-full border-t border-line text-left text-sm">
            <thead>
              <tr className="provenance">
                <th className="pb-1 pt-2 pr-3 font-normal">row</th>
                <th className="pb-1 pt-2 pr-3 font-normal">state</th>
                <th className="pb-1 pt-2 pr-3 font-normal">tries</th>
                <th className="pb-1 pt-2 font-normal">why</th>
              </tr>
            </thead>
            <tbody>
              {data.stuck_rows.map((row) => (
                <tr key={row.id} className="border-t border-line align-top">
                  <td className="provenance py-1.5 pr-3 break-all">
                    {row.concept_id ?? row.turn_id ?? row.id}
                  </td>
                  <td className="py-1.5 pr-3">
                    <Pill tone={row.state === "rejected" ? "contested" : "reported"}>
                      {row.state}
                    </Pill>
                  </td>
                  <td className="py-1.5 pr-3 text-ink" data-numeric>
                    {row.attempts}
                  </td>
                  <td className="py-1.5 text-xs text-ink-soft break-all">
                    {row.last_error ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </Section>
  );
}

export function OutboxPage() {
  const outbox = useOutbox();
  const drain = useDrainOutbox();
  const requeue = useRequeueOutbox();

  if (outbox.isLoading) return <SkeletonRows rows={4} />;

  const data = outbox.data;
  const channels = Object.entries(data?.channels ?? {});
  const owed = channels.reduce((n, [, c]) => n + c.owed, 0);
  const stuck = channels.reduce((n, [, c]) => n + c.stuck, 0);

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Outbox</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          What each score owes other modules, and whether it got there. A worker delivers it
          the moment the evaluation is saved and retries on its own when a module is down; an
          outage is waited out, never counted against the row. A row stops only when a module
          that is up keeps saying no — and then it is listed here, with the reason.
        </p>
      </header>

      <Section
        label="Worker"
        action={
          <span className="flex gap-2">
            <Btn
              size="sm"
              disabled={requeue.isPending || stuck === 0}
              onClick={() => requeue.mutate()}
            >
              {requeue.isPending ? "Requeueing…" : "Requeue stuck rows"}
            </Btn>
            <Btn
              variant="primary"
              size="sm"
              disabled={drain.isPending || owed === 0}
              onClick={() => drain.mutate()}
            >
              {drain.isPending ? "Delivering…" : "Deliver now"}
            </Btn>
          </span>
        }
      >
        <Panel className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <Pill tone={data?.sweeper.running ? "confirmed" : "reported"}>
              {data?.sweeper.running
                ? `running · every ${data.sweeper.interval_s}s and on every score`
                : "worker off — rows wait for “Deliver now”"}
            </Pill>
            <span className="provenance">{data?.url}</span>
            <Pill tone={data?.authenticated ? "confirmed" : "reported"}>
              {data?.authenticated ? "M04 service secret set" : "no M04 service secret"}
            </Pill>
          </div>

          {drain.data && (
            <p className="mt-3 border-t border-line pt-2 text-sm text-ink-soft" data-numeric>
              Delivered {drain.data.sent}, {drain.data.failed} not yet.
            </p>
          )}
          {requeue.data && (
            <p className="mt-3 border-t border-line pt-2 text-sm text-ink-soft" data-numeric>
              Requeued{" "}
              {Object.entries(requeue.data.requeued)
                .map(([name, n]) => `${n} for ${DESTINATIONS[name]?.title ?? name}`)
                .join(", ")}
              . Requeue after fixing the cause — a row M04 rejected will be rejected again.
            </p>
          )}
        </Panel>
      </Section>

      {channels.length === 0 ? (
        <Empty title="Nothing owed">
          <p>Every score this module has produced has reached the modules it owes.</p>
        </Empty>
      ) : (
        channels.map(([name, summary]) => <Channel key={name} name={name} data={summary} />)
      )}
    </>
  );
}

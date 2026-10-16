/**
 * "This looks wrong."
 *
 * §2.3. The dialog does two things and is careful about both.
 *
 * It does NOT change the score, and it does not pretend to. On success the
 * page is not refetched — a student who clicks and sees the same number
 * concludes the button is decorative. What they get instead is the backend's
 * own `student_message`, which promises a human within two days AND a fresh
 * question on the topic either way. That second half is the honest part: the
 * dispute might not be upheld, and a re-test is still the fastest way to move
 * a wrong mastery estimate.
 *
 * The re-test itself is M04's to schedule. The response carries the URL M13
 * called; the queue row belongs to M04, because a module writing another
 * module's table is how two sources of truth start.
 */

import { useEffect, useRef, useState } from "react";

import { useOpenDispute } from "../api";
import { Btn, Panel, Select, TextArea } from "../ui/primitives";

const REASONS = [
  { value: "misread_my_answer", label: "It misread what I said" },
  { value: "wrong_on_the_facts", label: "The reasoning is wrong on the facts" },
  { value: "quote_not_mine", label: "The quote isn't what I said" },
  { value: "too_harsh", label: "The score seems too harsh" },
  { value: "other", label: "Something else" },
];

export function DisputeDialog({
  evaluationId,
  dimensions,
  onClose,
}: {
  evaluationId: string;
  dimensions: string[];
  onClose: () => void;
}) {
  const [reason, setReason] = useState(REASONS[0].value);
  const [dimensionKey, setDimensionKey] = useState<string>(dimensions[0] ?? "");
  const [note, setNote] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const dispute = useOpenDispute();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="scrim-in fixed inset-0 z-50 flex items-start justify-center bg-ink/40 px-4 pt-[10vh] backdrop-blur-[2px]"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Report a problem with this score"
        onClick={(event) => event.stopPropagation()}
        className="dialog-in w-full max-w-lg"
      >
        <Panel className="shadow-raised">
          {dispute.data ? (
            <div className="px-5 py-5">
              <h2 className="text-section font-semibold text-ink">Thanks — that's logged.</h2>
              <p className="mt-2 text-sm text-ink">{dispute.data.student_message}</p>
              <p className="provenance mt-3">dispute {dispute.data.dispute_id}</p>
              <div className="mt-4 flex justify-end">
                <Btn variant="primary" size="sm" onClick={onClose}>
                  Close
                </Btn>
              </div>
            </div>
          ) : (
            <form
              className="px-5 py-5"
              onSubmit={(event) => {
                event.preventDefault();
                dispute.mutate({
                  evaluationId,
                  reason,
                  note,
                  dimensionKey: dimensionKey || null,
                });
              }}
            >
              <h2 className="text-section font-semibold text-ink">What looks wrong?</h2>
              <p className="mt-1 text-xs text-ink-soft">
                This does not change your score on its own. It puts the answer in front of a
                person, and books you a fresh question on the same topic either way.
              </p>

              <div className="mt-4 space-y-3">
                <Select
                  label="Which part"
                  value={dimensionKey}
                  onChange={(event) => setDimensionKey(event.target.value)}
                >
                  <option value="">The whole thing</option>
                  {dimensions.map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </Select>

                <Select
                  label="Reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                >
                  {REASONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>

                <TextArea
                  label="Anything to add"
                  hint="Optional. The reviewer reads this first."
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>

              {dispute.isError && (
                <p role="alert" className="mt-3 text-xs text-contested">
                  Could not file that: {(dispute.error as Error).message}
                </p>
              )}

              <div className="mt-4 flex justify-end gap-2">
                <Btn type="button" variant="ghost" size="sm" onClick={onClose}>
                  Cancel
                </Btn>
                <Btn type="submit" variant="primary" size="sm" disabled={dispute.isPending}>
                  {dispute.isPending ? "Sending…" : "Send"}
                </Btn>
              </div>
            </form>
          )}
        </Panel>
      </div>
    </div>
  );
}

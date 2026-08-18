/**
 * The student's own answer, with the quotes that earned each score marked in
 * place.
 *
 * This is the module's whole trust proposition rendered as an interface. Every
 * number M13 produces cites a span, every span is a pair of offsets into a
 * frozen artifact, and this component is where those offsets become something
 * a person can see. If it slices the text wrong, the product underlines words
 * the student did not say and captions them "what you said" — which is worse
 * than showing no evidence at all, because it looks like proof.
 *
 * Three rules follow from that, and each is enforced below rather than
 * documented:
 *
 * 1. **Never highlight an artifact whose checksum does not re-verify.** The
 *    backend recomputes `intact` from the stored bytes at read time. When it
 *    is false the offsets belong to text we no longer have, so the component
 *    renders the answer plainly and says why. Highlighting anyway would be
 *    guessing.
 *
 * 2. **Never highlight a span whose quote does not match the slice.** Even
 *    with an intact artifact, a mismatch means something upstream is wrong,
 *    and the honest response is to drop that one highlight rather than paint
 *    it at approximately the right place.
 *
 * 3. **A neutralised passage is labelled, not hidden.** Removing it would
 *    shift every later offset; blanking it silently would leave a student
 *    wondering why a paragraph earned nothing (EC-13.3).
 */

import { useMemo } from "react";

import type { DrawerArtifact, DrawerDimension } from "../types";
import { Pill } from "../ui/primitives";

/** One run of text with the set of dimensions citing it. */
interface Segment {
  start: number;
  end: number;
  text: string;
  dimensions: string[];
  blocked: boolean;
}

interface Marked {
  start: number;
  end: number;
  dimension: string | null;
  blocked: boolean;
}

/**
 * Cut the text at every span boundary, then label each run.
 *
 * Spans from different dimensions overlap routinely — the sentence that shows
 * correctness is often the sentence that shows communication — so a naive
 * "wrap each span" loop produces nested or duplicated markup and paints the
 * overlap twice. Splitting on the union of boundaries gives flat, disjoint
 * runs, each carrying every dimension that covers it.
 */
export function segment(text: string, marks: Marked[]): Segment[] {
  if (marks.length === 0) return [{ start: 0, end: text.length, text, dimensions: [], blocked: false }];

  const bounds = new Set<number>([0, text.length]);
  for (const mark of marks) {
    bounds.add(Math.max(0, Math.min(text.length, mark.start)));
    bounds.add(Math.max(0, Math.min(text.length, mark.end)));
  }
  const cuts = [...bounds].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const start = cuts[i];
    const end = cuts[i + 1];
    if (end <= start) continue;
    const covering = marks.filter((mark) => mark.start < end && mark.end > start);
    segments.push({
      start,
      end,
      text: text.slice(start, end),
      dimensions: [
        ...new Set(covering.map((m) => m.dimension).filter((d): d is string => d !== null)),
      ],
      blocked: covering.some((m) => m.blocked),
    });
  }
  return segments;
}

export function Transcript({
  artifact,
  dimensions,
  activeDimension,
  onSelectDimension,
}: {
  artifact: DrawerArtifact;
  dimensions: DrawerDimension[];
  /** Dimension whose spans are painted bright; null paints all of them soft. */
  activeDimension: string | null;
  onSelectDimension: (key: string | null) => void;
}) {
  const { segments, dropped } = useMemo(() => {
    if (!artifact.intact) return { segments: [], dropped: 0 };

    const marks: Marked[] = [];
    let mismatched = 0;

    for (const dimension of dimensions) {
      for (const span of dimension.spans) {
        if (span.artifact_id !== artifact.artifact_id) continue;
        // Rule 2. The backend already overwrites the model's quote with the
        // artifact's own text on repair, so a mismatch here means the record
        // and the artifact have diverged since — drop the highlight.
        if (artifact.text.slice(span.start, span.end) !== span.quote) {
          mismatched += 1;
          continue;
        }
        marks.push({
          start: span.start,
          end: span.end,
          dimension: dimension.dimension_key,
          blocked: false,
        });
      }
    }
    for (const [start, end] of artifact.neutralised) {
      marks.push({ start, end, dimension: null, blocked: true });
    }

    return { segments: segment(artifact.text, marks), dropped: mismatched };
  }, [artifact, dimensions]);

  if (!artifact.intact) {
    return (
      <div className="space-y-3">
        <p
          role="alert"
          className="rounded-panel border border-contested-line bg-contested-soft px-3 py-2 text-sm text-ink"
        >
          <strong className="font-semibold">Evidence highlighting is off for this answer.</strong>{" "}
          The stored text no longer matches the checksum recorded when it was scored, so the
          offsets cannot be trusted to point at the right words. The answer is shown below
          unmarked.
        </p>
        <AnswerBody>{artifact.text}</AnswerBody>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <AnswerBody>
        {segments.map((seg) => {
          if (seg.blocked) {
            return (
              <span
                key={seg.start}
                className="blocked-mark"
                title="Disregarded — this reads as an instruction to the grader, not as part of your answer."
              >
                {seg.text}
              </span>
            );
          }
          if (seg.dimensions.length === 0) return <span key={seg.start}>{seg.text}</span>;

          const isActive =
            activeDimension === null || seg.dimensions.includes(activeDimension);
          return (
            <mark
              key={seg.start}
              className={`${isActive ? "quote-mark quote-mark-active" : "quote-mark opacity-45"} cursor-pointer`}
              title={`Cited for: ${seg.dimensions.join(", ")}`}
              onClick={() =>
                onSelectDimension(
                  activeDimension === seg.dimensions[0] ? null : seg.dimensions[0],
                )
              }
            >
              {seg.text}
            </mark>
          );
        })}
      </AnswerBody>

      {dropped > 0 && (
        <p className="provenance text-contested">
          {dropped} span{dropped === 1 ? "" : "s"} not shown — the quote no longer matches the
          text at those offsets.
        </p>
      )}

      {artifact.neutralised.length > 0 && (
        <p className="text-xs text-ink-soft">
          <Pill tone="contested">disregarded</Pill>{" "}
          {artifact.neutralised.length === 1 ? "One passage was" : "Some passages were"} read as an
          instruction aimed at the grader rather than as part of the answer, and scored nothing.
          The rest of the answer was scored normally.
        </p>
      )}
    </div>
  );
}

function AnswerBody({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-answer whitespace-pre-wrap text-ink [text-wrap:pretty]">{children}</div>
  );
}

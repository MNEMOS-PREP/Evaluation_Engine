/**
 * How the answer was delivered — from M12, when M12 is running.
 *
 * The entire reason this component takes a `FusedAssessment` rather than a
 * `dict[str, float]`: every subscore arrives with a **disposition**, and only
 * `scored` may reach a numeric. M12's P0 validity gate is what makes its
 * facial-analysis work a contribution rather than a liability, and flattening
 * the shape one module downstream is how that gate silently stops being
 * enforced (AC-13.17).
 *
 * So a `coaching` or `diagnostic` signal renders as words with no number, and
 * a `suppressed` channel renders as its reason. A student who was not measured
 * has not performed badly — Rule 2, exactly.
 */

import type { DeliveryAssessment, DeliveryDisposition } from "../types";
import { Panel, Pill, Section } from "../ui/primitives";

const DISPOSITION_NOTE: Record<DeliveryDisposition, string> = {
  scored: "measured well enough to count",
  coaching: "shown as guidance only — not accurate enough to score",
  diagnostic: "recorded for diagnosis, not for scoring",
  suppressed: "not measured",
};

export function DeliverySection({ delivery }: { delivery: DeliveryAssessment | null }) {
  if (!delivery) {
    // Deliberately not an empty box. The module is absent; say so and say
    // what that costs, rather than leaving a gap that reads as a bug.
    return (
      <Section label="How you delivered it">
        <Panel className="border-dashed px-4 py-3">
          <p className="text-sm text-ink-soft">
            Not measured for this answer — pace, filler words and eye contact need the voice and
            video analysis, which isn't running yet. Nothing was marked down because of it: a
            signal we didn't measure counts as absent, not bad.
          </p>
        </Panel>
      </Section>
    );
  }

  const entries = Object.entries(delivery.subscores);

  return (
    <Section
      label="How you delivered it"
      meta={delivery.modality_config}
    >
      <Panel className="px-4 py-3">
        <ul className="space-y-2">
          {entries.map(([key, value]) => {
            const disposition = delivery.dispositions[key] ?? "suppressed";
            const scored = disposition === "scored";
            return (
              <li key={key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
                <span className="font-medium text-ink">{key.replace(/_/g, " ")}</span>
                <Pill tone={scored ? "confirmed" : "reported"}>
                  {DISPOSITION_NOTE[disposition as DeliveryDisposition]}
                </Pill>
                {scored && (
                  <span className="provenance ml-auto" data-numeric>
                    {value.toFixed(2)}
                  </span>
                )}
              </li>
            );
          })}
        </ul>

        {delivery.suppressed_channels.length > 0 && (
          <div className="mt-3 border-t border-line pt-2">
            <p className="rule-label">Not measured</p>
            <ul className="mt-1 space-y-0.5">
              {delivery.suppressed_channels.map((channel) => (
                <li key={channel} className="text-xs text-ink-soft">
                  <strong className="text-ink">{channel}</strong> —{" "}
                  {delivery.suppression_reasons[channel] ?? "no reason recorded"}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">
          Delivery never enters the overall score. It is reported beside the content judgement,
          not folded into it.
        </p>
      </Panel>
    </Section>
  );
}

/**
 * The rubrics, with every anchor visible.
 *
 * Published rather than buried, for two reasons that are really one. A student
 * is entitled to know what "level 3" means before being told they scored one,
 * and the hint-penalty table is a deduction applied to their score — master
 * plan §32.5 requires it to be transparent. Neither is a debugging convenience.
 *
 * The concept-bearing dimension is called out because it is the single most
 * consequential fact about a rubric: exactly one dimension's score becomes
 * mastery, and the loader refuses to load a rubric declaring zero or two.
 */

import { useState } from "react";

import { useRubric, useRubrics } from "../api";
import { Panel, Pill, Section, SkeletonRows } from "../ui/primitives";

export function RubricsPage() {
  const list = useRubrics();
  const [selected, setSelected] = useState<string | null>(null);
  const roundType = selected ?? list.data?.rubrics[0]?.round_type;
  const rubric = useRubric(roundType);

  if (list.isLoading) return <SkeletonRows rows={5} />;

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Rubrics</h1>
        <p className="provenance mt-1">rubric set {list.data?.rubric_set_version}</p>
      </header>

      <div className="mb-6 flex flex-wrap gap-1.5">
        {(list.data?.rubrics ?? []).map((summary) => (
          <button
            key={summary.round_type}
            type="button"
            onClick={() => setSelected(summary.round_type)}
            className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
              summary.round_type === roundType
                ? "border-brand-line bg-brand-soft text-brand"
                : "border-line bg-surface text-ink-soft hover:border-line-strong"
            }`}
          >
            {summary.round_type}
            <span className="provenance ml-1.5">v{summary.version}</span>
          </button>
        ))}
      </div>

      {rubric.isLoading && <SkeletonRows rows={4} />}

      {rubric.data && (
        <>
          <Section
            label="Dimensions"
            meta={`${rubric.data.dimensions.length} · rubric ${rubric.data.version}`}
          >
            <div className="space-y-3">
              {rubric.data.dimensions.map((dimension) => (
                <Panel key={dimension.key} className="px-4 py-3.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-ink">
                        {dimension.name}{" "}
                        <span className="provenance">{dimension.key}</span>
                      </p>
                      <p className="mt-0.5 text-sm text-ink-soft">{dimension.description}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                      {dimension.concept_bearing && (
                        <Pill tone="brand" title="This dimension's score becomes mastery in M04.">
                          concept-bearing
                        </Pill>
                      )}
                      <Pill tone="neutral">{dimension.concept_domain}</Pill>
                      <Pill tone="neutral" title="Relative weight in the composite.">
                        weight {dimension.weight}
                      </Pill>
                      {dimension.evidence_required && (
                        <Pill tone="confirmed">evidence required</Pill>
                      )}
                    </div>
                  </div>

                  {dimension.applies_when && (
                    <p className="provenance mt-2">
                      applies when {dimension.applies_when.field} {dimension.applies_when.op}{" "}
                      {JSON.stringify(dimension.applies_when.value)}
                    </p>
                  )}

                  <dl className="mt-3 space-y-1 border-t border-line pt-2">
                    {Object.entries(dimension.anchors)
                      .sort(([a], [b]) => Number(b) - Number(a))
                      .map(([level, text]) => (
                        <div key={level} className="flex gap-3 text-sm">
                          <dt
                            className="w-4 shrink-0 text-right font-mono text-xs text-ink-faint"
                            data-numeric
                          >
                            {level}
                          </dt>
                          <dd className="text-ink-soft">{text}</dd>
                        </div>
                      ))}
                  </dl>
                </Panel>
              ))}
            </div>
            <p className="mt-3 text-xs text-ink-soft">
              Every level has a behavioural anchor, and a rubric missing one fails to load rather
              than scoring with a gap. A dimension without an anchor at every level is prose, and
              prose is what a model will happily average into a number.
            </p>
          </Section>

          <Section label="Hint credit" title="What help costs">
            <Panel className="px-4 py-3">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="provenance">
                    <th className="pb-1 pr-4 font-normal">hints used</th>
                    <th className="pb-1 font-normal">credit</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(rubric.data.hint_penalty)
                    .sort(([a], [b]) => Number(a) - Number(b))
                    .map(([level, factor]) => (
                      <tr key={level} className="border-t border-line">
                        <td className="py-1 pr-4 text-ink" data-numeric>
                          {level === "0" ? "none" : `level ${level}`}
                        </td>
                        <td className="py-1 text-ink" data-numeric>
                          {(factor * 100).toFixed(0)}%
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <p className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">
                Published on purpose. More help never credits more — the loader rejects a table
                that rises — and the deduction is applied exactly once, in M13, so M04 does not
                apply it again on the way to mastery.
              </p>
            </Panel>
          </Section>

          {rubric.data.disqualifiers.length > 0 && (
            <Section label="Disqualifiers" title="Flags, not deductions">
              <Panel className="px-4 py-3">
                <ul className="space-y-2">
                  {rubric.data.disqualifiers.map((disqualifier) => (
                    <li key={disqualifier.key} className="text-sm">
                      <span className="font-medium text-ink">{disqualifier.key}</span>{" "}
                      <Pill tone="neutral">feeds {disqualifier.feeds}</Pill>
                      <p className="mt-0.5 text-ink-soft">{disqualifier.description}</p>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 border-t border-line pt-2 text-xs text-ink-soft">
                  There is deliberately no penalty field on a disqualifier. A student who
                  misremembers a function name is not one who invented a library, and a model
                  cannot reliably tell them apart — so this is reported prominently and routed to
                  M18's fabrication probe, and there is no arithmetic through which it could zero
                  a dimension.
                </p>
              </Panel>
            </Section>
          )}
        </>
      )}
    </>
  );
}

/**
 * Which upstreams are up, and what is switched off without them.
 *
 * Nothing here is marked required, and that is a design decision rather than
 * an oversight: marking one required turns someone else's outage into ours,
 * and this is the module that must not fail — a student's score cannot depend
 * on whether a downstream service happened to be up.
 *
 * `DependencyTable` comes from `@ai/core` so every module answers "why is this
 * page thin?" the same way.
 */

import { DependencyTable } from "@ai/core";

import { useDeps, useHealth, useModuleStatus } from "../api";
import { Field, Panel, Pill, Rows, Section, SkeletonRows } from "../ui/primitives";

export function DepsPage() {
  const deps = useDeps();
  const health = useHealth();
  const status = useModuleStatus();

  if (deps.isLoading) return <SkeletonRows rows={4} />;

  return (
    <>
      <header className="mb-8">
        <h1 className="text-title font-semibold text-ink">Dependencies</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-soft">
          M13 starts and runs with none of these present. What changes is the scope of what it can
          say, never the quality of what it does say.
        </p>
      </header>

      <Section label="This module">
        <Panel className="px-4 py-3">
          <Rows>
            <Field label="status">{health.data?.status ?? "unreachable"}</Field>
            <Field label="rubric set">
              <span className="break-all">{health.data?.rubric_set_version ?? "—"}</span>
            </Field>
            <Field label="calibration">{health.data?.calibration_version ?? "—"}</Field>
            {/* From the platform registry rather than from this module's own
                opinion of itself — the two disagreeing is worth seeing. */}
            <Field label="registry">
              {status.data
                ? `${status.data.id} · phase ${status.data.phase} · ${status.data.detail}`
                : "unreachable"}
            </Field>
            <Field label="reserved port">{status.data?.reserved_port ?? "—"}</Field>
          </Rows>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-2">
            <Pill tone={deps.data?.evaluation_available ? "confirmed" : "reported"}>
              {deps.data?.evaluation_available ? "scoring available" : "scoring off"}
            </Pill>
            <span className="provenance">
              {JSON.stringify(deps.data?.evaluator ?? {})}
            </span>
          </div>
          {!deps.data?.evaluation_available && (
            <p className="mt-2 text-xs text-ink-soft">
              No API key is configured. Scoring is the one feature that switches off without one,
              and the module reports that here rather than fabricating a number.
            </p>
          )}
        </Panel>
      </Section>

      <Section label="Upstream">
        <Panel className="overflow-x-auto px-4 py-3">
          <DependencyTable statuses={deps.data?.dependencies ?? []} />
        </Panel>
      </Section>
    </>
  );
}

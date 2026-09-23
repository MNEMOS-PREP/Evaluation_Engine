/**
 * M13 — Evaluation Engine · API client.
 *
 * Spec: plan_in_depth/M13_Evaluation_Engine.md §7 (API surface)
 *
 * One hook per backend endpoint, and no hook without one. The module's own
 * router says it best: "an endpoint that exists and returns a placeholder is
 * worse than one that does not." The same holds on this side — a screen that
 * shows a number the API never sent is the failure this whole module exists
 * to prevent, arriving through the front door.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@ai/core";
import type {
  CalibrationStatus,
  DepsResponse,
  DisputeOpened,
  DisputeQueue,
  DrainResult,
  EnsembleList,
  EvaluateRequestBody,
  EvidenceDrawer,
  Fixtures,
  ModuleStatus,
  Outbound,
  OutboxStatus,
  RequeueResult,
  RaterQueue,
  Rubric,
  RubricList,
  TurnEvaluation,
} from "./types";

export const m13Keys = {
  health: ["m13", "health"] as const,
  status: ["m13", "status"] as const,
  deps: ["m13", "deps"] as const,
  rubrics: ["m13", "rubrics"] as const,
  rubric: (roundType: string) => ["m13", "rubric", roundType] as const,
  ensembles: ["m13", "ensembles"] as const,
  fixtures: ["m13", "fixtures"] as const,
  evaluation: (turnId: string) => ["m13", "evaluation", turnId] as const,
  evidence: (turnId: string) => ["m13", "evidence", turnId] as const,
  outbound: (turnId: string) => ["m13", "outbound", turnId] as const,
  outbox: ["m13", "outbox"] as const,
  disputes: ["m13", "disputes"] as const,
  calibration: ["m13", "calibration"] as const,
  raterQueue: (raterId: string) => ["m13", "rater-queue", raterId] as const,
};

/* ------------------------------------------------------------------ */
/*  Meta                                                               */
/* ------------------------------------------------------------------ */

export interface Health {
  status: string;
  module: string;
  rubric_set_version: string;
  calibration_version: string;
}

export function useHealth() {
  return useQuery({
    queryKey: m13Keys.health,
    queryFn: () => api.get<Health>("/health"),
    retry: false,
  });
}

/** What the platform registry says this module is — not what it says itself. */
export function useModuleStatus() {
  return useQuery({
    queryKey: m13Keys.status,
    queryFn: () => api.get<ModuleStatus>("/status"),
    retry: false,
  });
}

export function useDeps() {
  return useQuery({
    queryKey: m13Keys.deps,
    queryFn: () => api.get<DepsResponse>("/v1/deps"),
    retry: false,
  });
}

/* ------------------------------------------------------------------ */
/*  Rubrics                                                            */
/* ------------------------------------------------------------------ */

export function useRubrics() {
  return useQuery({
    queryKey: m13Keys.rubrics,
    queryFn: () => api.get<RubricList>("/v1/rubrics"),
  });
}

export function useRubric(roundType: string | undefined) {
  return useQuery({
    queryKey: m13Keys.rubric(roundType ?? ""),
    enabled: Boolean(roundType),
    queryFn: () => api.get<Rubric>(`/v1/rubrics/${roundType}`),
  });
}

/**
 * The named ensembles the backend will accept.
 *
 * Fetched rather than hardcoded: the name is part of the calibration key, so a
 * list copied into the client drifts the moment a config is renamed and the
 * only symptom is a 422 the student sees.
 */
export function useEnsembles() {
  return useQuery({
    queryKey: m13Keys.ensembles,
    queryFn: () => api.get<EnsembleList>("/v1/ensembles"),
  });
}

export function useFixtures() {
  return useQuery({
    queryKey: m13Keys.fixtures,
    queryFn: () => api.get<Fixtures>("/v1/fixtures"),
  });
}

/* ------------------------------------------------------------------ */
/*  Evaluation                                                         */
/* ------------------------------------------------------------------ */

export function useEvaluate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: EvaluateRequestBody) =>
      api.post<TurnEvaluation>("/v1/evaluations", body),
    onSuccess: (evaluation) => {
      // Scoring writes the outbox and the M02/M19 payloads too, so anything
      // downstream of this turn is now stale.
      qc.invalidateQueries({ queryKey: m13Keys.evaluation(evaluation.turn_id) });
      qc.invalidateQueries({ queryKey: m13Keys.evidence(evaluation.turn_id) });
      qc.invalidateQueries({ queryKey: m13Keys.outbound(evaluation.turn_id) });
      qc.invalidateQueries({ queryKey: m13Keys.outbox });
    },
  });
}

export function useEvaluation(turnId: string | undefined) {
  return useQuery({
    queryKey: m13Keys.evaluation(turnId ?? ""),
    enabled: Boolean(turnId),
    retry: false,
    queryFn: () => api.get<TurnEvaluation>(`/v1/evaluations/${turnId}`),
  });
}

/** The drawer: frozen artifact text plus the spans that index into it. */
export function useEvidence(turnId: string | undefined) {
  return useQuery({
    queryKey: m13Keys.evidence(turnId ?? ""),
    enabled: Boolean(turnId),
    retry: false,
    queryFn: () => api.get<EvidenceDrawer>(`/v1/evaluations/${turnId}/evidence`),
  });
}

/** What this evaluation owes M04, M02 and M19 — real shapes, real ids. */
export function useOutbound(turnId: string | undefined) {
  return useQuery({
    queryKey: m13Keys.outbound(turnId ?? ""),
    enabled: Boolean(turnId),
    retry: false,
    queryFn: () => api.get<Outbound>(`/v1/evaluations/${turnId}/outbound`),
  });
}

/* ------------------------------------------------------------------ */
/*  The outbox (§6.11)                                                 */
/* ------------------------------------------------------------------ */

export function useOutbox() {
  return useQuery({
    queryKey: m13Keys.outbox,
    queryFn: () => api.get<OutboxStatus>("/v1/outbox"),
  });
}

export function useDrainOutbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<DrainResult>("/v1/outbox/drain", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: m13Keys.outbox }),
  });
}

/** Put held and rejected rows back in the queue — after the cause is fixed. */
export function useRequeueOutbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RequeueResult>("/v1/outbox/requeue", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: m13Keys.outbox }),
  });
}

/* ------------------------------------------------------------------ */
/*  Disputes (§2.3)                                                    */
/* ------------------------------------------------------------------ */

/**
 * "This score is wrong."
 *
 * Note what is NOT invalidated: the evaluation. Filing a dispute does not
 * change the score — it queues a human and asks M04 for a re-test — so
 * refetching would show the student an unchanged screen and teach them the
 * button did nothing. The backend's `student_message` says what happens next,
 * and the dialog shows that instead.
 */
export function useOpenDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      evaluationId,
      reason,
      note,
      dimensionKey,
    }: {
      evaluationId: string;
      reason: string;
      note?: string;
      dimensionKey?: string | null;
    }) =>
      api.post<DisputeOpened>(`/v1/evaluations/${evaluationId}/dispute`, {
        reason,
        note: note ?? "",
        dimension_key: dimensionKey ?? null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: m13Keys.disputes }),
  });
}

export function useDisputeQueue() {
  return useQuery({
    queryKey: m13Keys.disputes,
    queryFn: () => api.get<DisputeQueue>("/v1/disputes/queue"),
  });
}

export function useResolveDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      disputeId,
      upheld,
      note,
      resolvedBy,
    }: {
      disputeId: string;
      upheld: boolean;
      note?: string;
      resolvedBy?: string;
    }) =>
      api.post<{ id: string; state: string; resolved_at: string }>(
        `/v1/disputes/${disputeId}/resolve`,
        { upheld, note: note ?? "", resolved_by: resolvedBy ?? "unknown" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: m13Keys.disputes }),
  });
}

/* ------------------------------------------------------------------ */
/*  The calibration study (§6.6, §6.7)                                 */
/* ------------------------------------------------------------------ */

export function useCalibration() {
  return useQuery({
    queryKey: m13Keys.calibration,
    queryFn: () => api.get<CalibrationStatus>("/v1/calibration"),
  });
}

export function useRaterQueue(raterId: string) {
  return useQuery({
    queryKey: m13Keys.raterQueue(raterId),
    enabled: Boolean(raterId),
    queryFn: () =>
      api.get<RaterQueue>(`/v1/human-ratings/queue?rater_id=${encodeURIComponent(raterId)}`),
  });
}

export interface RatingBody {
  turn_id: string;
  question_id: string;
  candidate_id: string;
  rater_id: string;
  dimension_key: string;
  round_type: string;
  rubric_version: string;
  score: number;
  rater_confidence?: number | null;
  time_spent_s?: number;
  is_gold?: boolean;
  skipped?: boolean;
  consent_id?: string | null;
  purpose?: string;
}

export function useSubmitRating(raterId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RatingBody) => api.post<{ id: string }>("/v1/human-ratings", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: m13Keys.raterQueue(raterId) });
      // A rating changes the corpus the gate is fitted on.
      qc.invalidateQueries({ queryKey: m13Keys.calibration });
    },
  });
}

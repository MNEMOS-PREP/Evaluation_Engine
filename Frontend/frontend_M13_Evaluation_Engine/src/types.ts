/**
 * M13 — Evaluation Engine · the shapes the backend actually returns.
 *
 * Mirrored field-for-field from `Backend/backend_M13_Evaluation_Engine/`:
 * `contracts.py` for the stored record, `router.py` for the read models the
 * API composes on top of it. Where the two differ, the router wins — that is
 * what arrives over the wire.
 *
 * Two fields carry rules that no amount of typing can enforce, so they are
 * called out here and again where they are consumed:
 *
 * `calibrated_score`  null means NO NUMBER MAY BE SHOWN. Not "show the raw
 *                     score instead", not "show a dash and a tooltip" — the
 *                     dimension renders its reasoning and its evidence, and
 *                     the student is told why (§6.7, §2.4).
 *
 * `model_confidence`  never rendered to a student. It is the evaluator's
 *                     opinion of itself, it feeds ECE, and a student cannot
 *                     act on it. `agreement` is the badge (§8.1).
 */

/* ------------------------------------------------------------------ */
/*  Evidence                                                           */
/* ------------------------------------------------------------------ */

/** One verified quote, as `/evidence` flattens it for the drawer. */
export interface DrawerSpan {
  quote: string;
  start: number;
  end: number;
  /** Word-aligned playback offset from M11. Null until voice is wired. */
  t_ms: number | null;
  artifact_id: string;
  verified: boolean;
}

/**
 * The frozen text a span indexes into (§6.4 step 0).
 *
 * `intact` is recomputed by the backend at read time from the stored bytes.
 * When it is false the offsets are not trustworthy and the transcript must
 * refuse to highlight — see `Transcript.tsx`.
 */
export interface DrawerArtifact {
  artifact_id: string;
  artifact_type: "transcript" | "code" | "canvas" | string;
  text: string;
  checksum: string | null;
  intact: boolean;
  /** `[start, end)` ranges the evaluator was shown a block in place of. */
  neutralised: [number, number][];
}

export interface DrawerDimension {
  dimension_key: string;
  raw_score: number;
  credited_score: number;
  calibrated_score: number | null;
  reasoning: string;
  missing_key_points: string[];
  agreement: Agreement | null;
  spans: DrawerSpan[];
}

export interface EvidenceDrawer {
  turn_id: string;
  /** Resolves the rubric — `TurnEvaluation` carries only an opaque id. */
  round_type: string;
  rubric_version: string;
  artifact_checksums: Record<string, string>;
  artifacts: DrawerArtifact[];
  dimensions: DrawerDimension[];
}

/* ------------------------------------------------------------------ */
/*  The stored evaluation                                              */
/* ------------------------------------------------------------------ */

export type Agreement = "high" | "medium" | "low";
export type EvaluationStatus = "complete" | "needs_human_review" | "failed";
export type DeliveryDisposition = "scored" | "coaching" | "diagnostic" | "suppressed";

export interface EvidenceRef {
  span: (DrawerSpan & { artifact_type?: string }) | null;
  [key: string]: unknown;
}

export interface DimensionScore {
  dimension_key: string;
  raw_score: number;
  hint_level_used: number;
  credited_score: number;
  calibrated_score: number | null;
  evidence: EvidenceRef[];
  reasoning: string;
  missing_key_points: string[];
  /** Research instrument. Never rendered to a student — see the file header. */
  model_confidence: number;
  disqualifiers_triggered: string[];
}

export interface TokenUsage {
  tokens_in: number;
  tokens_out: number;
  cached_in: number;
  cache_write: number;
  cost_inr: number;
}

export interface EvaluatorOutput {
  evaluator_index: number;
  model_id: string;
  prompt_version: string;
  dimension_order_seed: number;
  scores: DimensionScore[];
  overall_note: string;
  latency_ms: number;
  tokens: TokenUsage;
  dropped_reason: string | null;
}

export interface DeliveryAssessment {
  subscores: Record<string, number>;
  dispositions: Record<string, DeliveryDisposition>;
  channel_contributions: Record<string, number>;
  confidence: number;
  suppressed_channels: string[];
  suppression_reasons: Record<string, string>;
  modality_config: string;
}

export interface VersionStamp {
  rubric_version: string | null;
  prompt_version: string | null;
  model_id: string | null;
  item_bank_version: string | null;
  calibration_version: string | null;
  code_sha: string | null;
  extractor_versions: Record<string, string>;
}

export interface TurnEvaluation {
  id: string;
  turn_id: string;
  candidate_id: string;
  session_id: string;
  rubric_id: string;
  artifact_checksums: Record<string, string>;
  key_point_coverage: Record<string, number>;
  scaffold_used: boolean;
  evaluators: EvaluatorOutput[];
  ensemble_config: string;
  /** `calibration` or `dev`. What these scores are FIT FOR (§11). */
  score_grade: string;
  aggregated: DimensionScore[];
  /** max − min, in whole rubric levels. One definition (§6.4). */
  spread_levels: Record<string, number>;
  agreement: Record<string, Agreement>;
  adjudicated: boolean;
  adjudication_note: string | null;
  composite: number | null;
  delivery: DeliveryAssessment | null;
  status: EvaluationStatus;
  versions: VersionStamp;
  consent_id: string | null;
  evaluated_at: string | null;
  superseded_by: string | null;
}

/* ------------------------------------------------------------------ */
/*  Rubrics                                                            */
/* ------------------------------------------------------------------ */

export interface RubricSummary {
  round_type: string;
  version: string;
  dimensions: string[];
  concept_bearing: string;
  hint_penalty: Record<string, number>;
}

export interface RubricList {
  rubric_set_version: string;
  rubrics: RubricSummary[];
}

export interface AppliesWhen {
  field: "modality" | "round_type" | "turn_kind";
  op: "eq" | "in";
  value: string | string[];
}

export interface RubricDimension {
  key: string;
  name: string;
  description: string;
  /** 0..4 → behavioural description. All five present, enforced at load. */
  anchors: Record<string, string>;
  weight: number;
  evidence_required: boolean;
  applies_when: AppliesWhen | null;
  concept_bearing: boolean;
  pairwise: boolean;
  concept_domain: "technical" | "communication";
}

export interface Disqualifier {
  key: string;
  description: string;
  feeds: "report_note" | "m18_probe" | "both";
}

export interface Rubric {
  id: string;
  version: string;
  round_type: string;
  dimensions: RubricDimension[];
  disqualifiers: Disqualifier[];
  hint_penalty: Record<string, number>;
  created_at: string;
  supersedes: string | null;
}

export interface EnsembleMember {
  model: string | null;
  dimension_order_seed: number;
}

export interface EnsembleConfig {
  name: string;
  size: number;
  members: EnsembleMember[];
  /** False for every shipped config — `run()` refuses to execute a true one. */
  homogeneous_without_decorrelation: boolean;
  /** A single member cannot produce one: it is not agreeing with anybody. */
  agreement_signal: boolean;
}

export interface EnsembleList {
  default: string;
  ensembles: EnsembleConfig[];
}

/* ------------------------------------------------------------------ */
/*  Fixtures — the bank M13 runs against while M05 is absent (§6.11)   */
/* ------------------------------------------------------------------ */

export interface FixtureQuestion {
  label: string;
  id: string;
  round_type: string;
}

export interface RegressionCase {
  label: string;
  question: string;
  expected_band: [number, number];
  /** Never `model`. A gate in the backend suite asserts it (Trap 9). */
  band_source: string;
  note: string;
}

export interface Fixtures {
  questions: FixtureQuestion[];
  regression_cases: RegressionCase[];
}

/* ------------------------------------------------------------------ */
/*  The outbound contract (CONTRACTS.md)                               */
/* ------------------------------------------------------------------ */

export interface ObservationPayload {
  id: string;
  candidate_id: string;
  concept_id: string;
  kind: string;
  outcome: number;
  raw_category: number;
  n_categories: number;
  response_model: string;
  item: unknown | null;
  source_dimension_key: string;
  weight: number;
  evidence: unknown[];
  consent_id: string | null;
  versions: VersionStamp;
  [key: string]: unknown;
}

export interface CoverageUpdate {
  turn_id: string;
  session_id: string;
  state: string;
  score: number;
  n_categories: number;
  rubric_version: string;
  scored_at: string;
}

export interface LedgerEntry {
  claim_kind: string;
  claim_key: string;
  value: number;
  evidence: unknown[];
  versions: VersionStamp;
  computed_at: string;
}

export interface Outbound {
  m04_observations: ObservationPayload[];
  m04_url: string;
  m02_coverage: CoverageUpdate | null;
  m19_ledger: LedgerEntry[];
  /** Set, loudly, when consent was absent and observations were withheld. */
  skipped: string | null;
}

/* ------------------------------------------------------------------ */
/*  Outbox, disputes, calibration, deps                                */
/* ------------------------------------------------------------------ */

export interface OutboxItem {
  id: string;
  concept_id: string;
  attempts: number;
  last_error: string | null;
}

export interface StuckRow {
  id: string;
  state: "held" | "rejected";
  attempts: number;
  failures: number;
  last_error: string | null;
  concept_id?: string;
  turn_id?: string;
  [key: string]: unknown;
}

/** One destination, as `ai_core.outbox.summary` reports it. */
export interface ChannelSummary {
  pending: number;
  sending: number;
  sent: number;
  void: number;
  held: number;
  rejected: number;
  owed: number;
  stuck: number;
  oldest_owed_s: number | null;
  next_retry_in_s: number | null;
  errors: { error: string; rows: number }[];
  stuck_rows: StuckRow[];
  configured?: boolean;
}

export interface SweeperStatus {
  running: boolean;
  interval_s: number;
  last_sweep_at: string | null;
}

export interface OutboxStatus {
  pending: number;
  url: string;
  authenticated: boolean;
  items: OutboxItem[];
  channels: Record<string, ChannelSummary>;
  sweeper: SweeperStatus;
}

export interface RequeueResult {
  requeued: Record<string, number>;
}

export interface DrainResult {
  sent: number;
  failed: number;
  pending: number;
  [key: string]: unknown;
}

export interface DisputeOpened {
  dispute_id: string;
  state: string;
  retest_url: string;
  student_message: string;
}

export interface Dispute {
  id: string;
  evaluation_id: string;
  /** The answer being challenged. Null if the evaluation was purged. */
  turn_id: string | null;
  dimension_key: string | null;
  reason: string;
  note: string;
  created_at: string;
}

export interface DisputeQueue {
  open: number;
  disputes: Dispute[];
}

export interface CalibrationThresholds {
  qwk_overall_min: number;
  qwk_dimension_min: number;
  length_bias_max: number;
  ece_max: number;
  min_fit_n: number;
}

export interface CalibrationRow {
  dimension_key: string;
  round_type: string;
  ensemble_config: string;
  method: string;
  n: number;
  qwk: number;
  display_numeric: boolean;
  /** Reason key → a sentence a human can read. Empty when the gate is open. */
  gate_reasons: Record<string, string>;
}

export interface CalibrationStatus {
  thresholds: CalibrationThresholds;
  fitted: CalibrationRow[];
}

export interface RaterQueueItem {
  turn_id: string;
  round_type: string;
}

export interface RaterQueue {
  rater_id: string;
  remaining: number;
  items: RaterQueueItem[];
  note: string;
}

export interface EvaluatorDescription {
  [key: string]: unknown;
}

export interface DepsResponse {
  module: string;
  dependencies: import("@ai/core").DependencyStatus[];
  degraded: import("@ai/core").DegradedFeature[];
  evaluation_available: boolean;
  evaluator: EvaluatorDescription;
}

/** `ai_core.modules_meta.ModuleStatus` — the platform registry's own row. */
export interface ModuleStatus {
  id: string;
  name: string;
  slug: string;
  phase: string;
  owner: string;
  implemented: boolean;
  spec: string;
  reserved_port: number;
  detail: string;
}

export interface EvaluateRequestBody {
  turn_id?: string;
  candidate_id?: string;
  session_id?: string;
  question_id?: string | null;
  question_label?: string | null;
  answer_text: string;
  code?: string | null;
  canvas?: string | null;
  hint_level_used?: number;
  consent_id?: string | null;
  round_type?: string | null;
  ensemble?: string;
  supersedes?: string | null;
}

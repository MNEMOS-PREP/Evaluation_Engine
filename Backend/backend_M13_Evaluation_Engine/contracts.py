"""M13 data contracts — spec §5.

These are the shapes four other modules read, so they are the part of this
module that is expensive to change later. Three rules govern them:

1. **Evidence types are not defined here.** `EvidenceSpan` and `EvidenceRef`
   live in `ai_core.evidence` (Platform_Core v0.2.0). M13 *produces* evidence;
   it does not get to decide what evidence is. Two copies of the type that
   carries "every number traces to evidence" is exactly how that sentence
   quietly stops being true in whichever repo falls behind.

2. **A field that cannot be enforced does not belong on the model.**
   `calibration_status` is deliberately absent from `RubricDimension`: it is a
   property of a fitted `CalibrationModel`, and putting it on a *versioned*
   rubric would make "we finished calibrating" a rubric bump — which §6.8
   turns into a batch re-score of the entire history (§6.7).

3. **Where a rule has a natural type, use the type rather than a convention.**
   `Disqualifier` is a flag with evidence and no numeric field, which is what
   makes §15.5's "never auto-zero" structural instead of a habit someone
   breaks in month six.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from ai_core.evidence import EvidenceRef
from ai_core.versions import VersionStamp
from pydantic import BaseModel, Field, model_validator

#: The rubric scale. 0..4 anchored ordinal, everywhere, forever (§6.1).
SCALE_MIN = 0
SCALE_MAX = 4
N_CATEGORIES = SCALE_MAX - SCALE_MIN + 1

#: Above this entailment score a key point counts as covered (§6.4 step 1).
#: Versioned because it moves scores: a change here changes every
#: `missing_key_points` list and therefore every checklist a student reads.
KP_ENTAILMENT_THRESHOLD = 0.5
#: The lexical fallback's own bar, far lower: a share of a key point's content
#: WORDS is not entailment, and a correct paraphrase routinely shares under
#: half of them. Below this, nearly every content word is absent — the one
#: case LexicalCoverage's docstring says it can be trusted with.
#: 1.1 (2026-10-04): the fallback used the entailment bar, so an answer the
#: evaluator judged complete was told it had covered none of the key points.
KP_LEXICAL_ABSENT_BELOW = 0.2
KP_THRESHOLD_VERSION = "1.1"


# ─────────────────────────────────────────────────────────────────────────
#  Telemetry
# ─────────────────────────────────────────────────────────────────────────


class TokenUsage(BaseModel):
    """One call's bill. Local, not `ai_core`, until a second module needs it.

    `cached_in` is here rather than folded into `tokens_in` because a cache
    that stops filling is invisible in a total: §11's per-call cost assumes an
    ~80% cached rubric prefix, and without the cached figure the bill simply
    triples with nothing on screen to say why.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cache_write: int = 0
    cost_inr: float = 0.0

    @property
    def cache_read_ratio(self) -> float:
        """Tracked metric; master plan §47.1 treats < 0.5 as a bug."""
        total = self.tokens_in + self.cached_in
        return self.cached_in / total if total else 0.0


# ─────────────────────────────────────────────────────────────────────────
#  Rubrics
# ─────────────────────────────────────────────────────────────────────────


class AppliesWhen(BaseModel):
    """A typed predicate, not an expression string (§6.1).

    The spec's earlier `applies_when: str  # "modality == 'coding'"` had no
    stated evaluator, and the natural implementation is `eval()` on a string
    read from a YAML file — a code-execution path inside the module every
    other module trusts. Two comparisons cover every example in the spec set,
    and an unknown `field` now fails at *load* rather than at scoring time.
    """

    field: Literal["modality", "round_type", "turn_kind"]
    op: Literal["eq", "in"]
    value: str | list[str]

    @model_validator(mode="after")
    def _value_matches_op(self) -> AppliesWhen:
        if self.op == "eq" and not isinstance(self.value, str):
            raise ValueError("op='eq' takes a string value")
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("op='in' takes a list value")
        return self

    def matches(self, context: dict[str, str]) -> bool:
        actual = context.get(self.field)
        if actual is None:
            return False
        return actual == self.value if self.op == "eq" else actual in self.value


class Disqualifier(BaseModel):
    """A flag with evidence, never a score modifier (§6.1, §15.5).

    There is deliberately no `penalty` field. A student who misremembers a
    function name is not one who invented a library, and the model cannot
    reliably tell them apart — so a disqualifier is reported prominently and
    routed to M18's fabrication probe, and there is no arithmetic through
    which it *could* zero a dimension.
    """

    key: str
    description: str
    feeds: Literal["report_note", "m18_probe", "both"] = "both"


class RubricDimension(BaseModel):
    key: str
    name: str
    description: str
    #: 0..4 → behavioural description. All five REQUIRED (§6.1, FR-13.1).
    anchors: dict[int, str]
    weight: float = Field(gt=0)
    evidence_required: bool = True
    applies_when: AppliesWhen | None = None
    #: EXACTLY ONE per rubric. This dimension's score becomes the M04
    #: observation for the concepts the question tests (§6.4 step 8).
    concept_bearing: bool = False
    #: Phase 2 (§6.5).
    pairwise: bool = False
    #: Communication-family dimensions may only map to communication concepts.
    #: Naming it on the dimension is what lets §6.4 step 8 route without
    #: re-deriving the rule from the key string.
    concept_domain: Literal["technical", "communication"] = "technical"

    @model_validator(mode="after")
    def _anchors_complete(self) -> RubricDimension:
        missing = [lvl for lvl in range(SCALE_MIN, SCALE_MAX + 1) if lvl not in self.anchors]
        if missing:
            raise ValueError(
                f"dimension '{self.key}' is missing anchors for {missing}. "
                "A dimension without a behavioural anchor at every level is prose, "
                "and prose is what §3.1 Trap 1 is about."
            )
        blank = [lvl for lvl, text in self.anchors.items() if not text.strip()]
        if blank:
            raise ValueError(f"dimension '{self.key}' has empty anchors at {blank}")
        return self


class Rubric(BaseModel):
    id: UUID
    version: str  # semver
    round_type: str
    dimensions: list[RubricDimension] = Field(min_length=1)
    disqualifiers: list[Disqualifier] = Field(default_factory=list)
    #: hint level → credited factor (§6.1). Published, not secret: master plan
    #: §32.5 requires the deduction to be transparent, and M04 §6.3 says the
    #: penalty is applied once, HERE.
    hint_penalty: dict[int, float] = Field(default_factory=dict)
    created_at: datetime
    supersedes: UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_concept_bearing(self) -> Rubric:
        bearing = [d.key for d in self.dimensions if d.concept_bearing]
        if len(bearing) != 1:
            raise ValueError(
                f"rubric {self.round_type}@{self.version} declares {len(bearing)} "
                f"concept-bearing dimensions ({bearing or 'none'}); exactly one is "
                "required (FR-13.22). Without it the natural implementation is a "
                "weighted mean, which silently folds communication into technical "
                "mastery — a value nobody chose and nobody can later untangle."
            )
        return self

    @model_validator(mode="after")
    def _hint_penalty_is_monotone(self) -> Rubric:
        if not self.hint_penalty:
            return self
        levels = sorted(self.hint_penalty)
        factors = [self.hint_penalty[lvl] for lvl in levels]
        if any(f > 1.0 or f <= 0.0 for f in factors):
            raise ValueError("hint credit factors must lie in (0, 1]")
        # Consecutive pairs; `strict` is wrong here because the second sequence
        # is deliberately one shorter.
        if any(b > a for a, b in zip(factors, factors[1:], strict=False)):
            raise ValueError("more help must never credit more — hint_penalty must not increase")
        return self

    @property
    def concept_bearing_key(self) -> str:
        return next(d.key for d in self.dimensions if d.concept_bearing)

    def dimension(self, key: str) -> RubricDimension:
        for dim in self.dimensions:
            if dim.key == key:
                return dim
        raise KeyError(key)

    def applicable(self, context: dict[str, str]) -> list[RubricDimension]:
        return [
            d
            for d in self.dimensions
            if d.applies_when is None or d.applies_when.matches(context)
        ]

    def credit(self, hint_level: int) -> float:
        """The published factor for a hint level. Unlisted levels credit fully."""
        return self.hint_penalty.get(hint_level, 1.0)


# ─────────────────────────────────────────────────────────────────────────
#  Scores
# ─────────────────────────────────────────────────────────────────────────


class Agreement(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class DimensionScore(BaseModel):
    dimension_key: str
    #: 0..4 as produced. Schema-constrained by ENUM at the model boundary —
    #: structured outputs drop `minimum`/`maximum`, so EC-13.12's "schema
    #: rejection" only works as an enum (see `schemas.py`).
    raw_score: int = Field(ge=SCALE_MIN, le=SCALE_MAX)
    hint_level_used: int = 0
    #: raw × rubric.credit(hint_level). Applied ONCE, here (§6.1).
    credited_score: float = 0.0
    #: After Platt/isotonic. None while the display gate is closed (§6.7).
    calibrated_score: float | None = None
    #: FR-13.3 lives here, not in prose: a non-empty list is what enforces it.
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reasoning: str = ""
    missing_key_points: list[str] = Field(default_factory=list)
    #: SELF-REPORTED by the evaluator. Feeds ECE/Brier (AC-13.9).
    #: NEVER rendered to a student — a model's opinion of its own reliability
    #: is a research instrument, not a fact a student can act on (§8.1).
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    disqualifiers_triggered: list[str] = Field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)


class EvaluatorOutput(BaseModel):
    evaluator_index: int
    model_id: str
    prompt_version: str
    #: The decorrelating permutation (§6.4). Two calls to the same model with
    #: the same bytes are one sample twice — `claude-sonnet-5` and
    #: `claude-opus-5` reject `temperature`/`top_p`/`top_k` outright, so there
    #: is no sampling knob to vary and the permutation is the only lever.
    dimension_order_seed: int = 0
    scores: list[DimensionScore] = Field(default_factory=list)
    overall_note: str = ""
    latency_ms: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    #: Set when the evaluator was dropped after retries (§6.3).
    dropped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.dropped_reason is None and bool(self.scores)


class DeliveryDisposition(StrEnum):
    """Mirrors M12 §5. Carried through so M12 FR-12.10 stays enforceable here."""

    scored = "scored"
    coaching = "coaching"
    diagnostic = "diagnostic"
    suppressed = "suppressed"


class DeliveryAssessment(BaseModel):
    """M12's `FusedAssessment`, as far as M13 needs it.

    Replaced by the real import when M12 ships (Phase 3). It is **not** a
    `dict[str, float]`: flattening drops `disposition`, and once dropped, M12's
    P0 validity gate — the thing that makes the facial-analysis work a
    contribution rather than a liability — stops being enforceable one module
    downstream (AC-13.17). It also loses the suppression *reasons* M12 turns
    into genuinely useful UI ("couldn't measure — your camera was backlit").
    """

    subscores: dict[str, float] = Field(default_factory=dict)
    dispositions: dict[str, DeliveryDisposition] = Field(default_factory=dict)
    channel_contributions: dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0
    suppressed_channels: list[str] = Field(default_factory=list)
    suppression_reasons: dict[str, str] = Field(default_factory=dict)
    modality_config: str = "content_only"

    def scored_subscores(self) -> dict[str, float]:
        """Only signals that passed M12's validity protocol may reach a numeric."""
        return {
            key: value
            for key, value in self.subscores.items()
            if self.dispositions.get(key) is DeliveryDisposition.scored
        }


class EvaluationStatus(StrEnum):
    complete = "complete"
    needs_human_review = "needs_human_review"
    failed = "failed"


class TurnEvaluation(BaseModel):
    id: UUID
    turn_id: UUID
    #: For routing and retention only. NEVER reaches an `EvaluatorView`.
    candidate_id: UUID
    session_id: UUID
    rubric_id: UUID
    #: The frozen artifact set (§6.4 step 0). Spans are offsets into a mutable
    #: thing; without this an ASR correction silently invalidates every span.
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    key_point_coverage: dict[str, float] = Field(default_factory=dict)
    #: Was the NLI vector shown to the evaluator? The calibration fit must
    #: stratify on this or the corpus quietly spans two measurements (§6.4).
    scaffold_used: bool = False
    evaluators: list[EvaluatorOutput] = Field(default_factory=list)
    ensemble_config: str = "n1_dev"
    #: What these scores are FIT FOR (§11). A free-tier evaluation is a real
    #: evaluation with real verified evidence — it is simply not eligible to
    #: be displayed as a number or to enter the calibration corpus. Storing
    #: the grade on the row is what makes that enforceable later, when the
    #: corpus is assembled by a query rather than by whoever remembers.
    score_grade: str = "dev"
    aggregated: list[DimensionScore] = Field(default_factory=list)
    #: max − min. ONE definition (§6.4) — the earlier draft called it σ in the
    #: contract and max−min in the pipeline, and with N=3 on a 0–4 scale those
    #: disagree on common cases.
    spread_levels: dict[str, int] = Field(default_factory=dict)
    agreement: dict[str, Agreement] = Field(default_factory=dict)
    adjudicated: bool = False
    adjudication_note: str | None = None
    composite: float | None = None
    delivery: DeliveryAssessment | None = None
    status: EvaluationStatus = EvaluationStatus.complete
    versions: VersionStamp = Field(default_factory=VersionStamp)
    consent_id: UUID | None = None
    evaluated_at: datetime | None = None
    superseded_by: UUID | None = None

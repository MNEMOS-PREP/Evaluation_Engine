"""Orchestration for one turn — spec §6.4, steps 0 through 8.

    0  freeze the artifacts and hash them
    1  key-point coverage            (scaffold, recorded as such)
    2  fact-check                    — P1, deferred (§15.10)
    3  ensemble, N independent, decorrelated
    4  aggregate: median, spread, unioned evidence
    5  adjudicate when a dimension is ≥2 levels apart
    6  apply the published hint credit, ONCE
    7  calibrate + compose, both behind the display gate
    8  emit: M04 observations, M02 coverage, M19 ledger — all via the outbox

The composition rule is the part worth reading twice. `composite` is None
whenever any contributing dimension is display-suppressed, because a composite
computed over whichever subset happens to be calibrated is a different
measurement each week. Delivery never enters it at all: it arrives as
`TurnEvaluation.delivery` from M12 and renders in its own section.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from ai_core.timeutil import utcnow

from . import calibration as calib
from . import coverage as coverage_module
from . import emit as emit_module
from .adapters import QuestionPackage, get_delivery, get_questions
from .contracts import (
    Agreement,
    DimensionScore,
    EvaluationStatus,
    Rubric,
    TurnEvaluation,
    VersionStamp,
)
from .ensemble import N1_PRACTICE, EnsembleConfig, adjudicate, needs_adjudication
from .ensemble import run as run_ensemble
from .evaluator import EvaluationRequest
from .evidence import Artifact, ArtifactSet
from .llm import LLM, get_llm, grade_of
from .projection import project_for_evaluator
from .rubrics import get_rubric
from .schemas import PROMPT_VERSION

log = logging.getLogger(__name__)


@dataclass
class TurnInput:
    """One turn to score. Everything M6 would hand over."""

    turn_id: UUID
    candidate_id: UUID
    session_id: UUID
    question_id: UUID
    answer_text: str
    code: str | None = None
    canvas: str | None = None
    hint_level_used: int = 0
    consent_id: UUID | None = None
    round_type: str | None = None


def freeze_artifacts(turn: TurnInput) -> ArtifactSet:
    """§6.4 step 0. Snapshot and hash, then find injection without mutating."""
    artifacts = [
        Artifact(artifact_id=turn.turn_id, artifact_type="transcript", text=turn.answer_text)
    ]
    if turn.code is not None:
        artifacts.append(Artifact(artifact_id=uuid4(), artifact_type="code", text=turn.code))
    if turn.canvas is not None:
        artifacts.append(Artifact(artifact_id=uuid4(), artifact_type="canvas", text=turn.canvas))
    frozen = ArtifactSet.freeze(artifacts)
    frozen.detect_and_mark_injection()
    return frozen


def apply_hint_credit(scores: list[DimensionScore], rubric: Rubric, hint_level: int) -> None:
    """§6.1. Applied ONCE, here — M04 §6.3 says so and does not re-apply it.

    `raw_score` is untouched on purpose: the calibration corpus and the
    regression suite have to stay comparable across hinted and unhinted
    answers, so the deduction lives only on `credited_score`.
    """
    factor = rubric.credit(hint_level)
    for score in scores:
        score.hint_level_used = hint_level
        score.credited_score = round(score.raw_score * factor, 3)


def calibrate(
    scores: list[DimensionScore],
    *,
    round_type: str,
    ensemble_config: str,
    lookup: CalibrationLookup | None = None,
) -> None:
    """§6.4 step 7 / §6.7. Sets `calibrated_score`, or leaves it None.

    None is the normal case today and says something true: no fitted mapping
    exists for this (dimension, round_type, ensemble_config), so there is no
    number anyone is entitled to show.
    """
    if lookup is None:
        return
    for score in scores:
        fitted = lookup(score.dimension_key, round_type, ensemble_config)
        if fitted is None or not fitted.get("display_numeric"):
            score.calibrated_score = None
            continue
        score.calibrated_score = round(
            calib.apply_mapping(score.raw_score, fitted.get("params", {})), 3
        )


def compose(scores: list[DimensionScore], rubric: Rubric) -> float | None:
    """The content composite, or None if ANY dimension is suppressed."""
    if not scores or any(s.calibrated_score is None for s in scores):
        return None
    total = sum(rubric.dimension(s.dimension_key).weight for s in scores)
    if total <= 0:
        return None
    weighted = sum(
        (s.calibrated_score or 0.0) * rubric.dimension(s.dimension_key).weight for s in scores
    )
    return round(weighted / total, 3)


class CalibrationLookup:  # noqa: B903 - a Protocol would need a runtime import here
    """Resolves a fitted mapping. `store.calibration_lookup()` supplies one."""

    def __call__(
        self, dimension_key: str, round_type: str, ensemble_config: str
    ) -> dict | None:  # pragma: no cover - interface
        raise NotImplementedError


def evaluate_turn(
    turn: TurnInput,
    *,
    llm: LLM | None = None,
    rubric: Rubric | None = None,
    question: QuestionPackage | None = None,
    config: EnsembleConfig = N1_PRACTICE,
    scaffold: bool = True,
    lookup: CalibrationLookup | None = None,
    artifacts: ArtifactSet | None = None,
) -> TurnEvaluation:
    """Score one turn. Async in production (FR-13.19); synchronous here.

    A caller that intends to *store* the evaluation freezes the artifacts
    itself and passes them in, so the bytes the spans index into are the ones
    persisted. Freezing twice would mint fresh ids for the code and canvas
    artifacts, and every span pointing at them would resolve to nothing.
    """
    package = question or get_questions().get(turn.question_id, turn.round_type)
    if package is None:
        raise LookupError(f"no question package for {turn.question_id}")

    round_type = turn.round_type or package.round_type
    active_rubric = rubric or get_rubric(round_type)
    client = llm or get_llm()

    frozen = artifacts if artifacts is not None else freeze_artifacts(turn)

    # Step 1 — coverage. Shown to the evaluator only when `scaffold` is on,
    # and recorded either way, because the calibration fit stratifies on it.
    cover = coverage_module.score(turn.answer_text, package.key_points)
    scaffold_used = scaffold and cover.available

    view = project_for_evaluator(
        question_stem=package.stem,
        reference_answer=package.reference_answer,
        key_points=package.key_points,
        rubric=active_rubric,
        answer_text=turn.answer_text,
        code=turn.code,
        canvas=turn.canvas,
        key_point_coverage=cover.scores if scaffold_used else None,
    )
    request = EvaluationRequest(
        view=view,
        artifacts=frozen,
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        context={"round_type": round_type},
    )

    # Steps 3-5 — ensemble, aggregate, adjudicate.
    result = run_ensemble(request, config, llm=client)
    if needs_adjudication(result):
        result = adjudicate(request, result, llm=client)

    scores = result.aggregated
    for score in scores:
        # The checklist a student reads comes from the coverage measure, not
        # from the evaluator's memory of the key points.
        if cover.available and not score.missing_key_points:
            score.missing_key_points = cover.missing()

    apply_hint_credit(scores, active_rubric, turn.hint_level_used)
    calibrate(scores, round_type=round_type, ensemble_config=config.name, lookup=lookup)

    if not scores:
        status = EvaluationStatus.needs_human_review
    elif len(scores) < len(active_rubric.applicable({"round_type": round_type})):
        status = EvaluationStatus.needs_human_review
    else:
        status = EvaluationStatus.complete

    return TurnEvaluation(
        id=uuid4(),
        turn_id=turn.turn_id,
        candidate_id=turn.candidate_id,
        session_id=turn.session_id,
        rubric_id=active_rubric.id,
        artifact_checksums=frozen.checksums,
        key_point_coverage=cover.scores,
        scaffold_used=scaffold_used,
        evaluators=result.outputs,
        ensemble_config=config.name,
        score_grade=str(grade_of(client)),
        aggregated=scores,
        spread_levels=result.spread_levels,
        agreement=result.agreement or {s.dimension_key: Agreement.medium for s in scores},
        adjudicated=result.adjudicated,
        adjudication_note=result.adjudication_note,
        composite=compose(scores, active_rubric),
        delivery=get_delivery().for_turn(turn.turn_id),
        status=status,
        versions=VersionStamp(
            rubric_version=active_rubric.version,
            prompt_version=PROMPT_VERSION,
            model_id=config.name,
            item_bank_version=package.item.bank_version if package.item else "fixtures",
            extractor_versions={"key_point_coverage": cover.method},
        ),
        consent_id=turn.consent_id,
        evaluated_at=utcnow(),
    )


def outbound(
    evaluation: TurnEvaluation, rubric: Rubric, package: QuestionPackage
) -> dict[str, object]:
    """Everything this evaluation owes other modules (§6.4 step 8).

    Assembled in one place so a caller cannot send the M04 observation and
    forget the M02 ledger row — the failure that makes coverage an intention
    again. Observations are omitted, loudly, when consent is absent.
    """
    payload: dict[str, object] = {
        "ledger": emit_module.ledger_entries(evaluation),
        "coverage": emit_module.coverage_update(evaluation, rubric),
        "observations": [],
        "observations_skipped": None,
    }
    try:
        payload["observations"] = emit_module.observations_for(evaluation, rubric, package)
    except emit_module.NoConsent as exc:
        payload["observations_skipped"] = str(exc)
        log.warning("no observations emitted for turn %s: %s", evaluation.turn_id, exc)
    return payload


__all__ = [
    "CalibrationLookup",
    "TurnInput",
    "apply_hint_credit",
    "calibrate",
    "compose",
    "evaluate_turn",
    "freeze_artifacts",
    "outbound",
]

"""Orchestration for one turn — spec §6.4.

This is the M0–M3 slice of the pipeline: freeze, project, score with one
evaluator, apply the published hint credit, and compose. Steps 1–2 (NLI
coverage, fact-check), 3–5 at N>1 (ensemble, aggregate, adjudicate) and 8
(the M04 emit) land in milestones M4 and M5; the seams are here and named so
they are wired rather than retrofitted.

The composition rule is the part worth reading. `composite` is None whenever
any contributing dimension is display-suppressed, because a composite computed
over whichever subset happens to be calibrated is a different measurement each
week — the same discipline §2.4 applies to a single dimension, applied to the
headline number. Delivery is excluded by construction rather than by
convention: it never enters the content composite at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from ai_core.timeutil import utcnow

from .adapters import QuestionPackage, get_delivery, get_questions
from .contracts import (
    Agreement,
    DimensionScore,
    EvaluationStatus,
    Rubric,
    TurnEvaluation,
    VersionStamp,
)
from .evaluator import EvaluationRequest, evaluate_once
from .evidence import Artifact, ArtifactSet
from .llm import LLM, get_llm, grade_of
from .projection import project_for_evaluator
from .rubrics import get_rubric
from .schemas import PROMPT_VERSION

log = logging.getLogger(__name__)

#: The config this slice runs. N>1 arrives in milestone M4; naming it now
#: means the calibration key (§6.7) is right from the first stored row rather
#: than backfilled.
ENSEMBLE_SINGLE = "n1_dev"


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
        Artifact(
            artifact_id=turn.turn_id,
            artifact_type="transcript",
            text=turn.answer_text,
        )
    ]
    if turn.code is not None:
        artifacts.append(
            Artifact(artifact_id=uuid4(), artifact_type="code", text=turn.code)
        )
    if turn.canvas is not None:
        artifacts.append(
            Artifact(artifact_id=uuid4(), artifact_type="canvas", text=turn.canvas)
        )
    frozen = ArtifactSet.freeze(artifacts)
    frozen.detect_and_mark_injection()
    return frozen


def apply_hint_credit(scores: list[DimensionScore], rubric: Rubric, hint_level: int) -> None:
    """§6.1. Applied ONCE, here — M04 §6.3 says so explicitly and does not re-apply.

    `raw_score` is untouched on purpose: the calibration corpus and the
    regression suite have to stay comparable across hinted and unhinted
    answers, so the deduction lives only on `credited_score`.
    """
    factor = rubric.credit(hint_level)
    for score in scores:
        score.hint_level_used = hint_level
        score.credited_score = round(score.raw_score * factor, 3)


def compose(
    scores: list[DimensionScore], rubric: Rubric, *, display_numeric: bool = False
) -> float | None:
    """The content composite, or None.

    None while calibration is incomplete (which, in this slice, is always):
    §2.4's rule is that we would rather show no number than one we cannot
    defend, and the composite is the number a student remembers.
    """
    if not display_numeric or not scores:
        return None
    # Delivery is never a rubric dimension — it arrives as `TurnEvaluation.delivery`
    # from M12 and renders in its own section (§8.1, M19 FR-19.7). So every score
    # here is a content score, and the exclusion is structural rather than a filter
    # someone has to remember to write.
    if any(s.calibrated_score is None for s in scores):
        return None
    total_weight = sum(rubric.dimension(s.dimension_key).weight for s in scores)
    if total_weight <= 0:
        return None
    weighted = sum(
        (s.calibrated_score or 0.0) * rubric.dimension(s.dimension_key).weight for s in scores
    )
    return round(weighted / total_weight, 3)


def agreement_for(spread: int, *, single_evaluator: bool) -> Agreement:
    """What the badge shows.

    A single-evaluator run is never "high": one evaluator agreeing with itself
    is not evidence, and §8.1 forbids rendering it as though it were.
    """
    if single_evaluator:
        return Agreement.medium
    if spread >= 2:
        return Agreement.low
    return Agreement.high if spread == 0 else Agreement.medium


def evaluate_turn(
    turn: TurnInput,
    *,
    llm: LLM | None = None,
    rubric: Rubric | None = None,
    question: QuestionPackage | None = None,
) -> TurnEvaluation:
    """Score one turn. Async in production (FR-13.19); synchronous here."""
    package = question or get_questions().get(turn.question_id)
    if package is None:
        raise LookupError(f"no question package for {turn.question_id}")

    round_type = turn.round_type or package.round_type
    active_rubric = rubric or get_rubric(round_type)

    artifacts = freeze_artifacts(turn)
    view = project_for_evaluator(
        question_stem=package.stem,
        reference_answer=package.reference_answer,
        key_points=package.key_points,
        rubric=active_rubric,
        answer_text=turn.answer_text,
        code=turn.code,
        canvas=turn.canvas,
    )

    request = EvaluationRequest(
        view=view,
        artifacts=artifacts,
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        evaluator_index=0,
        context={"round_type": round_type},
    )
    client = llm or get_llm()
    output = evaluate_once(request, llm=client)

    scores = list(output.scores)
    apply_hint_credit(scores, active_rubric, turn.hint_level_used)

    spread = {s.dimension_key: 0 for s in scores}
    agreement = {
        key: agreement_for(value, single_evaluator=True) for key, value in spread.items()
    }

    if output.dropped_reason and not scores:
        status = EvaluationStatus.needs_human_review
    elif len(scores) < len(active_rubric.applicable({"round_type": round_type})):
        # Some dimension lost its evidence and therefore its score. The turn is
        # not failed — the student still gets reasoning for the rest.
        status = EvaluationStatus.needs_human_review
    else:
        status = EvaluationStatus.complete

    return TurnEvaluation(
        id=uuid4(),
        turn_id=turn.turn_id,
        candidate_id=turn.candidate_id,
        session_id=turn.session_id,
        rubric_id=active_rubric.id,
        artifact_checksums=artifacts.checksums,
        scaffold_used=False,
        evaluators=[output],
        ensemble_config=ENSEMBLE_SINGLE,
        score_grade=str(grade_of(client)),
        aggregated=scores,
        spread_levels=spread,
        agreement=agreement,
        composite=compose(scores, active_rubric),
        delivery=get_delivery().for_turn(turn.turn_id),
        status=status,
        versions=VersionStamp(
            rubric_version=active_rubric.version,
            prompt_version=PROMPT_VERSION,
            model_id=ENSEMBLE_SINGLE,
            item_bank_version=package.item.bank_version if package.item else "fixtures",
        ),
        consent_id=turn.consent_id,
        evaluated_at=utcnow(),
    )


__all__ = [
    "ENSEMBLE_SINGLE",
    "TurnInput",
    "agreement_for",
    "apply_hint_credit",
    "compose",
    "evaluate_turn",
    "freeze_artifacts",
]

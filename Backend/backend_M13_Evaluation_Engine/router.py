"""HTTP surface — spec §7.

Only the endpoints the M0–M3 slice can honestly serve are here. The rest of
§7 — disputes, calibration, the rater workbench, the re-score triggers —
arrive with the milestones that implement them (§14). An endpoint that exists
and returns a placeholder is worse than one that does not exist: a caller
writes against it and finds out later.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import llm as llm_module
from . import rubrics
from .adapters import get_questions, regression_cases
from .contracts import Rubric, TurnEvaluation
from .dependencies import deps
from .service import TurnInput, evaluate_turn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["evaluation"])


class EvaluateRequest(BaseModel):
    """What M6 posts when a turn finishes. Async in production (FR-13.19)."""

    turn_id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID = Field(default_factory=uuid4)
    session_id: UUID = Field(default_factory=uuid4)
    question_id: UUID | None = None
    #: Convenience for the fixture bank while M5 does not exist (§6.11).
    question_label: str | None = None
    answer_text: str
    code: str | None = None
    canvas: str | None = None
    hint_level_used: int = 0
    consent_id: UUID | None = None
    round_type: str | None = None


@router.get("/deps")
def dependencies() -> dict:
    """Which upstreams are up, and what breaks without them (§6.11)."""
    return {
        "module": "M13",
        "dependencies": [d.model_dump(mode="json") for d in deps().statuses()],
        "degraded": [f.model_dump(mode="json") for f in deps().degraded()],
        "evaluation_available": llm_module.is_available(),
    }


@router.get("/rubrics")
def list_rubrics() -> dict:
    loaded = rubrics.load_all()
    return {
        "rubric_set_version": rubrics.rubric_set_version(),
        "rubrics": [
            {
                "round_type": rubric.round_type,
                "version": rubric.version,
                "dimensions": [d.key for d in rubric.dimensions],
                "concept_bearing": rubric.concept_bearing_key,
                "hint_penalty": rubric.hint_penalty,
            }
            for rubric in sorted(loaded.values(), key=lambda r: r.round_type)
        ],
    }


@router.get("/rubrics/{round_type}", response_model=Rubric)
def get_rubric(round_type: str) -> Rubric:
    try:
        return rubrics.get_rubric(round_type)
    except rubrics.RubricError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/fixtures")
def list_fixtures() -> dict:
    """The bank M13 runs against when M5 is absent, and the regression cases."""
    questions = get_questions().all()
    return {
        "questions": [
            {"label": q.label, "id": str(q.question_id), "round_type": q.round_type}
            for q in questions
        ],
        "regression_cases": [
            {
                "label": c.label,
                "question": c.question_label,
                "expected_band": list(c.expected_band),
                "band_source": c.band_source,
                "note": c.note,
            }
            for c in regression_cases()
        ],
    }


@router.post("/evaluations", response_model=TurnEvaluation)
def create_evaluation(request: EvaluateRequest) -> TurnEvaluation:
    source = get_questions()
    package = None
    if request.question_label is not None and hasattr(source, "by_label"):
        package = source.by_label(request.question_label)
    elif request.question_id is not None:
        package = source.get(request.question_id)

    if package is None:
        raise HTTPException(
            status_code=404,
            detail="no question package — pass question_id, or question_label for the fixture bank",
        )

    turn = TurnInput(
        turn_id=request.turn_id,
        candidate_id=request.candidate_id,
        session_id=request.session_id,
        question_id=package.question_id,
        answer_text=request.answer_text,
        code=request.code,
        canvas=request.canvas,
        hint_level_used=request.hint_level_used,
        consent_id=request.consent_id,
        round_type=request.round_type,
    )

    try:
        return evaluate_turn(turn, question=package)
    except rubrics.RubricError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

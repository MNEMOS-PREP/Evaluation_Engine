"""HTTP surface — spec §7.

Only endpoints this module can honestly serve. An endpoint that exists and
returns a placeholder is worse than one that does not: a caller writes against
it and finds out later.

The outbound half of the contract — what M13 *sends* — is not here. It lives
in `emit.py` and is delivered by `delivery.py`'s sweeper, because a student's
score must never wait on another module answering.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid

from ai_core import outbox as core_outbox
from ai_core.db import get_session
from ai_core.evidence import sha256_hex
from ai_core.guard import candidate_guard, require_candidate, require_role
from ai_core.identity import Principal, Role
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import calibration as calib
from . import delivery, rubrics, store
from . import emit as emit_module
from . import llm as llm_module
from .adapters import get_questions, regression_cases
from .contracts import Rubric, TurnEvaluation
from .dependencies import deps
from .ensemble import CONFIGS, N1_PRACTICE
from .models import Calibration, CoverageOutbox, HumanRating, ObservationOutbox
from .rubrics import get_rubric as _get_rubric
from .service import TurnInput, evaluate_turn, freeze_artifacts, outbound

log = logging.getLogger(__name__)

def enforce_access(request: Request, session: Session = Depends(get_session)) -> Principal | None:
    """Who may ask — Platform_Core's `candidate_guard` (v0.11.0).

    Until 2026-10-02 M13 checked nobody: a student's evaluation, its evidence
    and the exact request M13 sent its evaluators were readable by anybody
    holding a turn id. An evaluation is about one student, so its routes are
    resolved to that student — by turn or by evaluation id, through the
    request's own database session — and the guard decides. Routes that name
    nobody (rubrics, ensembles, fixtures, calibration) stay open.
    """

    def by_turn(turn_id: str) -> str | None:
        try:
            row = store.latest_for_turn(session, uuid.UUID(turn_id))
        except ValueError:
            return None
        return str(row.candidate_id) if row is not None else None

    def by_evaluation(evaluation_id: str) -> str | None:
        try:
            row = store.get_evaluation(session, uuid.UUID(evaluation_id))
        except ValueError:
            return None
        return str(row.candidate_id) if row is not None else None

    return candidate_guard({"turn_id": by_turn, "evaluation_id": by_evaluation})(request)


router = APIRouter(prefix="/v1", tags=["evaluation"], dependencies=[Depends(enforce_access)])

#: The operator's routes: the outbox, the dispute queue, the raters. They name
#: no student, so the guard above let them through, and until 2026-10-02 any
#: browser could read every open dispute, drain or requeue the outbox, or
#: submit human ratings into the calibration study (Platform_Core v0.12.0).
#: Administrators only — a placement officer has no part in how M13 scores.
operator_only = require_role(Role.admin)

#: The two rating routes only. The calibration study needs at least three raters
#: and an administrator cannot be three people: reviewers (faculty, seniors) may
#: rate answers and nothing else here — not the outbox, not disputes.
rater_access = require_role(Role.admin, Role.reviewer)


class EvaluateRequest(BaseModel):
    """What M6 posts when a turn finishes. Async in production (FR-13.19)."""

    turn_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    #: Absent means "the student asking" — the playground's case. It used to
    #: mean a random id, which the guard then refused: a student scoring their
    #: own answer in the shell got "This is not your record."
    candidate_id: uuid.UUID | None = None
    session_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    question_id: uuid.UUID | None = None
    #: Convenience for the fixture bank while M5 does not exist (§6.11).
    question_label: str | None = None
    answer_text: str
    code: str | None = None
    canvas: str | None = None
    hint_level_used: int = 0
    consent_id: uuid.UUID | None = None
    round_type: str | None = None
    ensemble: str = N1_PRACTICE.name
    #: Set when re-scoring: the evaluation this one replaces (§6.8).
    supersedes: uuid.UUID | None = None
    #: M11's FR-11.15: ranges of `answer_text` the speech recogniser was
    #: unsure of. Read and scored; never quoted as evidence.
    uncitable: list[tuple[int, int]] = Field(default_factory=list, max_length=40)
    #: 2026-10-22, from M06: the interviewer's corrective prompts (a
    #: pushback, a simpler question) that an answer needed before it came
    #: right — priced like hints, with the rubric's own published credit, so a
    #: correct answer and one that became correct with help do not score alike.
    prompts_used: int = Field(default=0, ge=0, le=10)
    #: 2026-10-22, from M06: the key points of what was actually asked, for a
    #: question asked one part at a time. Absent means all of them.
    key_point_ids: list[str] | None = Field(default=None, max_length=40)


class DisputeRequest(BaseModel):
    reason: str
    note: str = ""
    dimension_key: str | None = None


class ResolveRequest(BaseModel):
    upheld: bool
    note: str = ""
    resolved_by: str = "unknown"


class RatingRequest(BaseModel):
    """One rater's judgement — §6.6. All three MFRM facets are required."""

    turn_id: uuid.UUID
    question_id: uuid.UUID
    candidate_id: uuid.UUID
    rater_id: str
    dimension_key: str
    round_type: str
    rubric_version: str
    score: int = Field(ge=0, le=4)
    rater_confidence: int | None = None
    time_spent_s: int = 0
    is_gold: bool = False
    skipped: bool = False
    consent_id: uuid.UUID | None = None
    purpose: str = "research"


# ── meta ─────────────────────────────────────────────────────────────────


@router.get("/deps")
def dependencies() -> dict:
    """Which upstreams are up, and what breaks without them (§6.11)."""
    return {
        "module": "M13",
        "dependencies": [d.model_dump(mode="json") for d in deps().statuses()],
        "degraded": [f.model_dump(mode="json") for f in deps().degraded()],
        "evaluation_available": llm_module.is_available(),
        "evaluator": llm_module.describe(),
    }


@router.get("/rubrics")
def list_rubrics() -> dict:
    loaded = rubrics.load_all()
    return {
        "rubric_set_version": rubrics.rubric_set_version(),
        "rubrics": [
            {
                "round_type": r.round_type,
                "version": r.version,
                "dimensions": [d.key for d in r.dimensions],
                "concept_bearing": r.concept_bearing_key,
                "hint_penalty": r.hint_penalty,
            }
            for r in sorted(loaded.values(), key=lambda r: r.round_type)
        ],
    }


@router.get("/rubrics/{round_type}", response_model=Rubric)
def get_rubric(round_type: str) -> Rubric:
    try:
        return rubrics.get_rubric(round_type)
    except rubrics.RubricError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ensembles")
def list_ensembles() -> dict:
    """The named ensembles a caller may ask for.

    Published because the name is part of the calibration key (§6.7) — a
    caller choosing one is choosing which fitted mapping their scores will be
    read against, and a client that hardcodes the list drifts the moment a
    config is renamed. `POST /v1/evaluations` 422s on an unknown name; this is
    how you avoid finding that out at runtime.
    """
    return {
        "default": N1_PRACTICE.name,
        "ensembles": [
            {
                "name": config.name,
                "size": config.size,
                "members": [
                    {"model": member.model, "dimension_order_seed": member.seed}
                    for member in config.members
                ],
                # False for every shipped config, by construction: `run()`
                # refuses to execute one that would report determinism as
                # agreement (FR-13.26).
                "homogeneous_without_decorrelation": config.homogeneous_without_decorrelation(),
                "agreement_signal": config.size > 1,
            }
            for config in sorted(CONFIGS.values(), key=lambda c: c.size)
        ],
    }


@router.get("/fixtures")
def list_fixtures() -> dict:
    """The bank M13 runs against when M5 is absent, and the regression cases."""
    return {
        "questions": [
            {"label": q.label, "id": str(q.question_id), "round_type": q.round_type}
            for q in get_questions().all()
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


# ── evaluation ───────────────────────────────────────────────────────────


@router.post("/evaluations", response_model=TurnEvaluation)
def create_evaluation(
    request: EvaluateRequest,
    session: Session = Depends(get_session),
    principal: Principal | None = Depends(enforce_access),
) -> TurnEvaluation:
    # The body names the student; the caller (M06's outbox) forwards them.
    if request.candidate_id is None:
        own = principal.candidate_id if principal is not None else None
        request.candidate_id = uuid.UUID(own) if own else uuid.uuid4()
    require_candidate(principal, request.candidate_id)
    source = get_questions()
    package = None
    if request.question_label is not None and hasattr(source, "by_label"):
        package = source.by_label(request.question_label)
    elif request.question_id is not None:
        package = source.get(request.question_id, request.round_type)
    if package is None:
        raise HTTPException(
            status_code=404,
            detail="no question package — pass question_id, or question_label for the fixtures",
        )

    config = CONFIGS.get(request.ensemble)
    if config is None:
        raise HTTPException(
            status_code=422, detail=f"unknown ensemble '{request.ensemble}'; have {sorted(CONFIGS)}"
        )
    if request.key_point_ids:
        # Only what the question asked is what the answer is judged against —
        # never an empty list, which would judge it against nothing.
        wanted = set(request.key_point_ids)
        scoped = [kp for kp in package.key_points if kp.id in wanted]
        if scoped:
            package = dataclasses.replace(package, key_points=scoped)

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
        uncitable=list(request.uncitable),
        prompts_used=request.prompts_used,
    )
    # Frozen HERE rather than inside `evaluate_turn`, so the bytes the spans
    # index into are the exact bytes stored beside the evaluation.
    frozen = freeze_artifacts(turn)
    try:
        rubric = _get_rubric(turn.round_type or package.round_type)
        evaluation = evaluate_turn(
            turn,
            question=package,
            config=config,
            lookup=store.calibration_lookup(session),
            artifacts=frozen,
        )
    except rubrics.RubricError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_evaluation(
        session,
        evaluation,
        outbound(evaluation, rubric, package),
        question_id=package.question_id,
        round_type=rubric.round_type,
        artifacts=frozen,
    )
    if request.supersedes is not None:
        store.supersede(session, request.supersedes, evaluation.id)
    # Out in milliseconds rather than at the next sweep. The sweep is the
    # safety net for the rows that fail, not the delivery mechanism.
    delivery.kick()
    return evaluation


@router.get("/evaluations/{turn_id}", response_model=TurnEvaluation)
def read_evaluation(turn_id: uuid.UUID, session: Session = Depends(get_session)) -> TurnEvaluation:
    row = store.latest_for_turn(session, turn_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no evaluation for that turn")
    return TurnEvaluation.model_validate(row.payload)


def _artifacts_for_drawer(row: store.Evaluation, evaluation: TurnEvaluation) -> list[dict]:
    """The frozen text a span resolves against, with its integrity re-checked.

    `intact` is recomputed from the stored bytes rather than trusted, and the
    drawer must not highlight when it is false. An offset into text that is no
    longer the text we scored would underline the wrong words and caption them
    "what you said" — which is the one failure this module cannot have.
    """
    out = []
    for artifact_id, stored in (row.artifacts or {}).items():
        text = stored.get("text", "")
        expected = evaluation.artifact_checksums.get(artifact_id)
        out.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": stored.get("artifact_type", "transcript"),
                "text": text,
                "checksum": stored.get("checksum"),
                "intact": bool(expected) and sha256_hex(text) == expected,
                # Ranges the evaluator was shown a block in place of (EC-13.3).
                # Surfaced so the drawer can say WHICH passage was disregarded
                # instead of leaving a student to wonder why it earned nothing.
                "neutralised": [list(r) for r in stored.get("neutralised", [])],
            }
        )
    return out


@router.get("/evaluations/{turn_id}/evidence")
def read_evidence(turn_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    """Verified spans with playback offsets — what the evidence drawer renders."""
    row = store.latest_for_turn(session, turn_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no evaluation for that turn")
    evaluation = TurnEvaluation.model_validate(row.payload)
    return {
        "turn_id": str(turn_id),
        # The rubric behind these scores. `TurnEvaluation` carries `rubric_id`
        # and nothing that resolves it, so without this a reader holding an
        # evaluation cannot fetch the dimension names or the anchors — and a
        # drawer that shows `communication: 3` with no way to say what level 3
        # means is back to the unanchored prose §3.1 Trap 1 is about.
        "round_type": row.round_type,
        "rubric_version": row.rubric_version,
        "artifact_checksums": evaluation.artifact_checksums,
        "artifacts": _artifacts_for_drawer(row, evaluation),
        "dimensions": [
            {
                "dimension_key": s.dimension_key,
                "raw_score": s.raw_score,
                "credited_score": s.credited_score,
                "calibrated_score": s.calibrated_score,
                "reasoning": s.reasoning,
                "missing_key_points": s.missing_key_points,
                "agreement": evaluation.agreement.get(s.dimension_key),
                "spans": [
                    {
                        "quote": ref.span.quote,
                        "start": ref.span.start,
                        "end": ref.span.end,
                        "t_ms": ref.span.t_ms,
                        "artifact_id": str(ref.span.artifact_id),
                        "verified": ref.span.verified,
                    }
                    for ref in s.evidence
                    if ref.span is not None
                ],
            }
            for s in evaluation.aggregated
        ],
    }


@router.get("/evaluations/{turn_id}/outbound")
def read_outbound(turn_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    """Exactly what this evaluation owes M04, M02 and M19.

    Exposed so a sibling module can be developed against real shapes before
    either side is wired — which is the difference between a merge and a
    debugging session.
    """
    row = store.latest_for_turn(session, turn_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no evaluation for that turn")
    evaluation = TurnEvaluation.model_validate(row.payload)
    package = (
        get_questions().get(row.question_id, row.round_type)
        if row.question_id
        else None
    )
    if package is None:
        raise HTTPException(status_code=409, detail="question package is no longer resolvable")
    payload = outbound(evaluation, _get_rubric(row.round_type), package)
    return {
        "m04_observations": [o.as_payload() for o in payload.get("observations", [])],
        "m04_url": emit_module.observations_url(evaluation.candidate_id),
        "m02_coverage": payload.get("coverage"),
        "m19_ledger": payload.get("ledger"),
        "skipped": payload.get("observations_skipped"),
    }


# ── the outbox ───────────────────────────────────────────────────────────


def _describe_observation(row: ObservationOutbox) -> dict:
    return {"id": str(row.observation_id), "concept_id": row.concept_id,
            "candidate_id": str(row.candidate_id)}


def _describe_coverage(row: CoverageOutbox) -> dict:
    return {"id": str(row.id), "turn_id": str(row.turn_id), "session_id": str(row.session_id)}


@router.get("/outbox", dependencies=[Depends(operator_only)])
def outbox_status(session: Session = Depends(get_session)) -> dict:
    """What is owed, to whom, and every row that is stuck — with its reason.

    A rejected row used to vanish from this view (`pending: 0`, `items: []`)
    and the only place to read why was the database. It is listed now,
    because a row nobody can see is a row nobody fixes.
    """
    pending = store.pending_observations(session, limit=1000)
    return {
        # The original shape, which the outbox page reads.
        "pending": len(pending),
        "url": emit_module.m04_base_url(),
        # Always, since Platform_Core v0.12.0: with nothing configured the
        # machine secret is sent. Kept for the outbox page, which reads it.
        "authenticated": bool(emit_module.service_headers()),
        "items": [
            {"id": str(r.observation_id), "concept_id": r.concept_id, "attempts": r.attempts,
             "last_error": r.last_error}
            for r in pending[:20]
        ],
        # Per destination, stuck rows included.
        "channels": {
            "m04.observations": core_outbox.summary(
                session, ObservationOutbox, describe=_describe_observation
            ),
            "m02.coverage": {
                **core_outbox.summary(session, CoverageOutbox, describe=_describe_coverage),
                "configured": emit_module.coverage_url("s", "c", "t") is not None,
            },
        },
        "sweeper": delivery.sweeper().status(),
    }


@router.post("/outbox/drain", dependencies=[Depends(operator_only)])
def outbox_drain(session: Session = Depends(get_session)) -> dict:
    """Deliver what is due, now. Idempotent; safe to call repeatedly.

    Not how rows normally leave — the sweeper does that, and the evaluation
    that wrote them kicks it. This is for a person who wants to watch it happen.
    """
    return store.drain(session)


@router.post("/outbox/requeue", dependencies=[Depends(operator_only)])
def outbox_requeue(session: Session = Depends(get_session)) -> dict:
    """Put held and rejected rows back in the queue, after the cause is fixed.

    `failures` resets; `attempts` is kept, because the history is still true.
    """
    counts = {
        "m04.observations": core_outbox.requeue(session, ObservationOutbox),
        "m02.coverage": core_outbox.requeue(session, CoverageOutbox),
    }
    delivery.kick()
    return {"requeued": counts}


# ── disputes (§2.3) ──────────────────────────────────────────────────────


@router.post("/evaluations/{evaluation_id}/dispute")
def create_dispute(
    evaluation_id: uuid.UUID, request: DisputeRequest, session: Session = Depends(get_session)
) -> dict:
    row = store.get_evaluation(session, evaluation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such evaluation")
    dispute = store.open_dispute(
        session,
        evaluation_id=evaluation_id,
        candidate_id=row.candidate_id,
        reason=request.reason,
        note=request.note,
        dimension_key=request.dimension_key,
    )
    return {
        "dispute_id": str(dispute.id),
        "state": dispute.state,
        # The half that matters: M04 owns the retest_queue row, so we ask for
        # a dispute rather than reaching into another module's table.
        "retest_url": emit_module.retest_url(
            row.candidate_id, request.dimension_key or "unknown"
        ),
        "student_message": (
            "Thanks. A human will look at this within 2 days, and I've scheduled a "
            "fresh question on this topic for your next session either way."
        ),
    }


@router.get("/disputes/queue", dependencies=[Depends(operator_only)])
def dispute_queue(session: Session = Depends(get_session)) -> dict:
    rows = list(store.open_disputes(session))
    # A dispute names the evaluation it challenges — a specific reading of an
    # answer, which a re-score supersedes. A reviewer needs the *answer*, so
    # the turn is resolved here rather than leaving every caller to do the
    # lookup and one of them to link at the wrong id.
    turns = {
        d.id: (
            row.turn_id if (row := store.get_evaluation(session, d.evaluation_id)) else None
        )
        for d in rows
    }
    return {
        "open": len(rows),
        "disputes": [
            {
                "id": str(d.id),
                "evaluation_id": str(d.evaluation_id),
                "turn_id": str(turns[d.id]) if turns[d.id] else None,
                "dimension_key": d.dimension_key,
                "reason": d.reason,
                "note": d.note,
                "created_at": d.created_at.isoformat(),
            }
            for d in rows
        ],
    }


@router.post("/disputes/{dispute_id}/resolve")
def resolve(
    dispute_id: uuid.UUID,
    request: ResolveRequest,
    session: Session = Depends(get_session),
    operator: Principal = Depends(operator_only),
) -> dict:
    # Who resolved it is who is signed in. `resolved_by` in the body was the
    # stand-in for that before there was anybody to ask, and the screen sent
    # "unknown"; it is kept for old callers and no longer trusted.
    row = store.resolve_dispute(
        session,
        dispute_id,
        upheld=request.upheld,
        note=request.note,
        resolved_by=operator.subject,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no such dispute")
    return {"id": str(row.id), "state": row.state, "resolved_at": row.resolved_at.isoformat()}


# ── the calibration study (§6.6) ─────────────────────────────────────────


@router.post("/human-ratings")
def submit_rating(
    request: RatingRequest,
    session: Session = Depends(get_session),
    rater: Principal = Depends(rater_access),
) -> dict:
    data = request.model_dump()
    if rater.role is Role.reviewer:
        # The RATER facet is what the agreement analysis is built on. A reviewer
        # rates as themselves; a body that names someone else is not believed.
        data["rater_id"] = rater.subject
    row = HumanRating(**data)
    session.add(row)
    session.commit()
    return {"id": str(row.id)}


@router.get("/human-ratings/queue")
def rating_queue(
    rater_id: str = Query(...),
    limit: int = Query(20, le=100),
    session: Session = Depends(get_session),
    rater: Principal = Depends(rater_access),
) -> dict:
    """Turns this rater has not yet rated.

    Audio and transcripts are de-identified before they reach a peer rater
    (§6.6, AC-13.15) — that lives in the workbench surface, not here, and this
    endpoint deliberately returns ids rather than content until it does.
    """
    if rater.role is Role.reviewer:
        rater_id = rater.subject
    rated = {
        r.turn_id
        for r in session.exec(select(HumanRating).where(HumanRating.rater_id == rater_id)).all()
    }
    rows = session.exec(
        select(store.Evaluation).where(store.Evaluation.superseded_by.is_(None))  # type: ignore[union-attr]
    ).all()
    queue = [r for r in rows if r.turn_id not in rated][:limit]
    return {
        "rater_id": rater_id,
        "remaining": len(queue),
        "items": [{"turn_id": str(r.turn_id), "round_type": r.rubric_version} for r in queue],
        "note": "de-identified rendering is required before a peer rater sees content (AC-13.15)",
    }


@router.get("/calibration")
def list_calibration(session: Session = Depends(get_session)) -> dict:
    rows = session.exec(
        select(Calibration).where(Calibration.superseded_by.is_(None))  # type: ignore[union-attr]
    ).all()
    return {
        "thresholds": {
            "qwk_overall_min": calib.QWK_OVERALL_MIN,
            "qwk_dimension_min": calib.QWK_DIMENSION_MIN,
            "length_bias_max": calib.LENGTH_BIAS_MAX,
            "ece_max": calib.ECE_MAX,
            "min_fit_n": calib.MIN_FIT_N,
        },
        "fitted": [
            {
                "dimension_key": c.dimension_key,
                "round_type": c.round_type,
                "ensemble_config": c.ensemble_config,
                "method": c.method,
                "n": c.fitted_on_n,
                "qwk": c.qwk,
                "display_numeric": c.display_numeric,
                "gate_reasons": c.gate_reasons,
            }
            for c in rows
        ],
    }

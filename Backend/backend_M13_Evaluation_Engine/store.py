"""Persistence and the outbox drain.

Two jobs. Store an evaluation with everything needed to explain it later, and
get its consequences to the modules that need them without ever letting one of
those modules' outages become a student's problem.

**The outbox is the whole point of this file.** An evaluation and its outbound
rows are written in one transaction; a worker drains them afterwards
(`delivery.py`, on `ai_core.outbox`). So M04 being down delays a mastery update
and does not fail an evaluation — and because the row carries M04's own
content-hashed id, a replay is an insert conflict there rather than a second
answer.

**A re-score appends.** `supersede()` points the old row at the new one and
retracts the observation that came from it, because M04 recomputes from
surviving observations rather than compensating with an inverse (M04 §6.2).
Overwriting would leave θ carrying both readings of the same answer.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

from ai_core import outbox as core_outbox
from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from . import delivery
from . import emit as emit_module
from .contracts import TurnEvaluation
from .evidence import ArtifactSet
from .models import (
    Calibration,
    CoverageOutbox,
    Dispute,
    DisputeState,
    Evaluation,
    ObservationOutbox,
    OutboxState,
)

log = logging.getLogger(__name__)

#: Answered failures before a row is held for a person. The policy's, named
#: here because callers have always read it from this module.
MAX_OUTBOX_ATTEMPTS = core_outbox.RetryPolicy().max_failures


def frozen_artifacts(artifacts: ArtifactSet | None) -> dict:
    """The artifact set as stored JSON — text included, on purpose.

    `neutralised` travels with it because a student is owed the reason a
    passage of their own answer was disregarded, and that reason cannot be
    recomputed later without re-running the detector at whatever version it
    has drifted to by then.
    """
    if artifacts is None:
        return {}
    return {
        str(artifact_id): {
            "artifact_type": artifact.artifact_type,
            "text": artifact.text,
            "checksum": artifact.checksum,
            "neutralised": [list(r) for r in artifacts.neutralised.get(artifact_id, [])],
        }
        for artifact_id, artifact in artifacts.artifacts.items()
    }


def save_evaluation(
    session: Session,
    evaluation: TurnEvaluation,
    outbound: dict[str, object],
    *,
    question_id: uuid.UUID | None = None,
    round_type: str = "",
    artifacts: ArtifactSet | None = None,
) -> Evaluation:
    """Write the evaluation and queue its consequences, in one transaction."""
    row = Evaluation(
        id=evaluation.id,
        turn_id=evaluation.turn_id,
        candidate_id=evaluation.candidate_id,
        session_id=evaluation.session_id,
        rubric_id=evaluation.rubric_id,
        rubric_version=evaluation.versions.rubric_version or "unknown",
        question_id=question_id,
        round_type=round_type,
        ensemble_config=evaluation.ensemble_config,
        score_grade=evaluation.score_grade,
        status=str(evaluation.status),
        scaffold_used=evaluation.scaffold_used,
        payload=evaluation.model_dump(mode="json"),
        artifacts=frozen_artifacts(artifacts),
        evaluated_at=evaluation.evaluated_at or utcnow(),
    )
    session.add(row)

    for observation in outbound.get("observations") or []:
        session.add(
            ObservationOutbox(
                observation_id=observation.id,
                evaluation_id=evaluation.id,
                candidate_id=observation.candidate_id,
                concept_id=observation.concept_id,
                kind=observation.kind,
                payload=observation.as_payload(),
            )
        )

    coverage = outbound.get("coverage")
    if (
        isinstance(coverage, dict)
        and coverage.get("score") is not None
        and emit_module.coverage_url(
            evaluation.session_id, evaluation.candidate_id, evaluation.turn_id
        )
    ):
        # Only when an M02 is configured: a queue for a module this deployment
        # does not run is a queue that is owed for ever.
        session.add(
            CoverageOutbox(
                evaluation_id=evaluation.id,
                turn_id=evaluation.turn_id,
                session_id=evaluation.session_id,
                candidate_id=evaluation.candidate_id,
                payload=coverage,
            )
        )

    session.commit()
    session.refresh(row)
    return row


def get_evaluation(session: Session, evaluation_id: uuid.UUID) -> Evaluation | None:
    return session.get(Evaluation, evaluation_id)


def latest_for_turn(session: Session, turn_id: uuid.UUID) -> Evaluation | None:
    """The live evaluation — the one nothing supersedes."""
    return session.exec(
        select(Evaluation)
        .where(Evaluation.turn_id == turn_id, Evaluation.superseded_by.is_(None))  # type: ignore[union-attr]
        .order_by(Evaluation.evaluated_at.desc())  # type: ignore[union-attr]
    ).first()


def supersede(session: Session, old_id: uuid.UUID, new_id: uuid.UUID) -> None:
    """A re-score: point the old row forward and retract what it emitted.

    Retract rather than compensate. M04 recomputes mastery from surviving
    observations, so an inverse update would be a second belief about the same
    answer rather than the removal of the first (M04 §6.2, FR-13.29).
    """
    old = session.get(Evaluation, old_id)
    if old is None:
        return
    old.superseded_by = new_id
    session.add(old)

    for row in session.exec(
        select(ObservationOutbox).where(ObservationOutbox.evaluation_id == old_id)
    ).all():
        if row.state in (OutboxState.pending, OutboxState.sending):
            # Never sent, so nothing to retract — just stop it going. `void`,
            # not `rejected`: nothing is wrong, and a rejected row is listed as
            # needing a person.
            row.state = OutboxState.void
            row.last_error = "superseded before send"
        elif row.state == OutboxState.void:
            continue
        else:
            payload = dict(row.payload)
            payload["retracted"] = True
            payload["retraction_reason"] = "rescore"
            row.payload = payload
            row.state = OutboxState.pending
            row.attempts = 0
            row.failures = 0
            row.next_attempt_at = None
        session.add(row)

    # The old score's coverage row: stop it if it has not gone. If it has, the
    # new evaluation's row carries the new score, and M02's ledger keeps both —
    # "scored 0.5, re-scored 0.75" is the sequence a dispute needs.
    for row in session.exec(
        select(CoverageOutbox).where(CoverageOutbox.evaluation_id == old_id)
    ).all():
        if row.state in (OutboxState.pending, OutboxState.sending):
            row.state = OutboxState.void
            row.last_error = "superseded before send"
            session.add(row)
    session.commit()


# ─────────────────────────────────────────────────────────────────────────
#  The drain
# ─────────────────────────────────────────────────────────────────────────


def pending_observations(session: Session, limit: int = 100) -> list[ObservationOutbox]:
    """Observations still owed to M04 — waiting, backing off, or in flight."""
    return list(
        session.exec(
            select(ObservationOutbox)
            .where(ObservationOutbox.state.in_(core_outbox.OPEN_STATES))  # type: ignore[union-attr]
            .order_by(ObservationOutbox.created_at)  # type: ignore[arg-type]
            .limit(limit)
        ).all()
    )


def drain(
    session: Session, sender: delivery.LegacySender | None = None, limit: int = 100
) -> dict:
    """Send what is due, now. Safe to run repeatedly and safe to interrupt.

    What `POST /v1/outbox/drain` and the suite call. The sweeper does the same
    thing on its own schedule; this is the same pass, on demand.

    With a `sender`, only the M04 channel runs, through that sender — the
    suite's fakes speak the old `(candidate_id, observations) -> (ok, detail)`
    shape, and a test must never reach a real M02.
    """
    if sender is not None:
        channels = [delivery.observation_channel(delivery.from_legacy(sender))]
    else:
        channels = delivery.channels()
    reports = [core_outbox.deliver(session, channel, limit=limit) for channel in channels]
    failed = sum(r.retried + r.held + r.rejected + r.deferred for r in reports)
    return {
        "sent": sum(r.moved for r in reports),
        "failed": failed,
        "pending": len(pending_observations(session, limit)),
        "channels": [r.as_dict() for r in reports],
    }


class Sender:  # noqa: B903 - callable interface, kept simple for injection
    def __call__(
        self, candidate_id: uuid.UUID, observations: list[dict]
    ) -> tuple[bool, str]:  # pragma: no cover - interface
        raise NotImplementedError


def http_sender(candidate_id: uuid.UUID, observations: list[dict]) -> tuple[bool, str]:
    """POST to M04 in the legacy `(ok, detail)` shape. Never raises."""
    outcome = core_outbox.post_json(
        emit_module.observations_url(candidate_id),
        {"observations": observations},
        headers={
            **emit_module.service_headers(),
            "X-Role": "student",
            "X-Candidate-Id": str(candidate_id),
        },
    )
    return outcome.ok, outcome.detail


# ─────────────────────────────────────────────────────────────────────────
#  Calibration lookup — what the display gate reads
# ─────────────────────────────────────────────────────────────────────────


def calibration_lookup(session: Session):
    """A resolver for `service.calibrate`, keyed exactly as §6.7 requires."""

    def lookup(dimension_key: str, round_type: str, ensemble_config: str) -> dict | None:
        row = session.exec(
            select(Calibration)
            .where(
                Calibration.dimension_key == dimension_key,
                Calibration.round_type == round_type,
                Calibration.ensemble_config == ensemble_config,
                Calibration.superseded_by.is_(None),  # type: ignore[union-attr]
            )
            .order_by(Calibration.fitted_at.desc())  # type: ignore[union-attr]
        ).first()
        if row is None:
            return None
        return {
            "display_numeric": row.display_numeric,
            "params": row.params,
            "method": row.method,
            "gate_reasons": row.gate_reasons,
        }

    return lookup


def save_calibration(session: Session, fit) -> Calibration:  # noqa: ANN001 - calibration.Fit
    """Store a fit, superseding any previous one for the same key."""
    previous = session.exec(
        select(Calibration).where(
            Calibration.dimension_key == fit.dimension_key,
            Calibration.round_type == fit.round_type,
            Calibration.ensemble_config == fit.ensemble_config,
            Calibration.superseded_by.is_(None),  # type: ignore[union-attr]
        )
    ).all()

    row = Calibration(
        dimension_key=fit.dimension_key,
        round_type=fit.round_type,
        ensemble_config=fit.ensemble_config,
        method=fit.method,
        params=fit.params,
        fitted_on_n=fit.n,
        scaffold_stratum=fit.scaffold_stratum,
        qwk=fit.qwk,
        qwk_overall=fit.qwk_overall,
        krippendorff_alpha=fit.alpha,
        ece=fit.ece,
        length_bias_beta=fit.beta,
        display_numeric=fit.gate.display_numeric,
        gate_reasons=fit.gate.reasons,
    )
    session.add(row)
    session.flush()
    for old in previous:
        old.superseded_by = row.id
        session.add(old)
    session.commit()
    session.refresh(row)
    return row


# ─────────────────────────────────────────────────────────────────────────
#  Disputes (§2.3)
# ─────────────────────────────────────────────────────────────────────────


def open_dispute(
    session: Session,
    *,
    evaluation_id: uuid.UUID,
    candidate_id: uuid.UUID,
    reason: str,
    note: str = "",
    dimension_key: str | None = None,
) -> Dispute:
    row = Dispute(
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
        dimension_key=dimension_key,
        reason=reason,
        note=note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def open_disputes(session: Session) -> Iterator[Dispute]:
    yield from session.exec(
        select(Dispute)
        .where(Dispute.state == DisputeState.open)
        .order_by(Dispute.created_at)  # type: ignore[arg-type]
    ).all()


def resolve_dispute(
    session: Session, dispute_id: uuid.UUID, *, upheld: bool, note: str, resolved_by: str
) -> Dispute | None:
    row = session.get(Dispute, dispute_id)
    if row is None:
        return None
    row.state = DisputeState.upheld if upheld else DisputeState.rejected
    row.resolution_note = note
    row.resolved_by = resolved_by
    row.resolved_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


__all__ = [
    "MAX_OUTBOX_ATTEMPTS",
    "Sender",
    "calibration_lookup",
    "drain",
    "get_evaluation",
    "http_sender",
    "latest_for_turn",
    "open_dispute",
    "open_disputes",
    "pending_observations",
    "resolve_dispute",
    "save_calibration",
    "save_evaluation",
    "supersede",
]

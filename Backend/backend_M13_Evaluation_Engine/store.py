"""Persistence and the outbox drain.

Two jobs. Store an evaluation with everything needed to explain it later, and
get its consequences to the modules that need them without ever letting one of
those modules' outages become a student's problem.

**The outbox is the whole point of this file.** An evaluation and its outbound
rows are written in one transaction; a worker drains them afterwards. So M04
being down delays a mastery update and does not fail an evaluation — and
because the row carries M04's own content-hashed id, a replay is an insert
conflict there rather than a second answer.

**A re-score appends.** `supersede()` points the old row at the new one and
retracts the observation that came from it, because M04 recomputes from
surviving observations rather than compensating with an inverse (M04 §6.2).
Overwriting would leave θ carrying both readings of the same answer.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from . import emit as emit_module
from .contracts import TurnEvaluation
from .models import Calibration, Dispute, DisputeState, Evaluation, ObservationOutbox, OutboxState

log = logging.getLogger(__name__)

#: Give up re-sending after this many attempts and leave the row visible.
MAX_OUTBOX_ATTEMPTS = 5


def save_evaluation(
    session: Session,
    evaluation: TurnEvaluation,
    outbound: dict[str, object],
    *,
    question_id: uuid.UUID | None = None,
    round_type: str = "",
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
        if row.state == OutboxState.pending:
            # Never sent, so nothing to retract — just stop it going.
            row.state = OutboxState.rejected
            row.last_error = "superseded before send"
        else:
            payload = dict(row.payload)
            payload["retracted"] = True
            payload["retraction_reason"] = "rescore"
            row.payload = payload
            row.state = OutboxState.pending
            row.attempts = 0
        session.add(row)
    session.commit()


# ─────────────────────────────────────────────────────────────────────────
#  The drain
# ─────────────────────────────────────────────────────────────────────────


def pending_observations(session: Session, limit: int = 100) -> list[ObservationOutbox]:
    return list(
        session.exec(
            select(ObservationOutbox)
            .where(
                ObservationOutbox.state == OutboxState.pending,
                ObservationOutbox.attempts < MAX_OUTBOX_ATTEMPTS,
            )
            .order_by(ObservationOutbox.created_at)  # type: ignore[arg-type]
            .limit(limit)
        ).all()
    )


def drain(session: Session, sender: Sender | None = None, limit: int = 100) -> dict[str, int]:
    """Send what is pending. Safe to run repeatedly and safe to interrupt.

    Groups by candidate because M04's endpoint is per-candidate and takes a
    LIST in one transaction — the 60ms budget in its §11 is per call, not per
    observation.
    """
    rows = pending_observations(session, limit)
    if not rows:
        return {"sent": 0, "failed": 0, "pending": 0}

    send = sender or http_sender
    by_candidate: dict[uuid.UUID, list[ObservationOutbox]] = {}
    for row in rows:
        by_candidate.setdefault(row.candidate_id, []).append(row)

    sent = failed = 0
    for candidate_id, batch in by_candidate.items():
        ok, detail = send(candidate_id, [dict(r.payload) for r in batch])
        for row in batch:
            row.attempts += 1
            if ok:
                row.state = OutboxState.sent
                row.sent_at = utcnow()
                row.last_error = None
                sent += 1
            else:
                row.last_error = detail[:400]
                # A 4xx will not become a 2xx on a retry; a 5xx might.
                if detail.startswith("http_4") and not detail.startswith("http_429"):
                    row.state = OutboxState.rejected
                failed += 1
            session.add(row)
    session.commit()
    return {"sent": sent, "failed": failed, "pending": len(pending_observations(session, limit))}


class Sender:  # noqa: B903 - callable interface, kept simple for injection
    def __call__(
        self, candidate_id: uuid.UUID, observations: list[dict]
    ) -> tuple[bool, str]:  # pragma: no cover - interface
        raise NotImplementedError


def http_sender(candidate_id: uuid.UUID, observations: list[dict]) -> tuple[bool, str]:
    """POST to M04. Never raises — a transport failure is a retry, not a crash."""
    import json  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    body = json.dumps({"observations": observations}).encode("utf-8")
    request = urllib.request.Request(
        emit_module.observations_url(candidate_id),
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "M13-EvaluationEngine/0.1",
            **emit_module.service_headers(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300, f"http_{response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:  # noqa: BLE001 - an outage must not become ours
        return False, f"{type(exc).__name__}: {exc}"


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

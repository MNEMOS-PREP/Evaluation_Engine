"""What M13 sends other modules — spec §6.4 step 8. Milestone M5.

This is the module's real output. A score that stays inside M13 is a demo; the
artifacts below are what four other modules read, so their shapes are the
expensive thing to get wrong and the reason this file is mostly contract.

    M04   one observation per (turn, concept), evidence-linked, θ-eligible
          only when the item was calibrated. THE mastery write path.
    M02   the coverage-ledger row moves to `scored`, which is what makes
          coverage a guarantee rather than an intention (M02 §6).
    M19   a ledger entry per dimension score, append-only, with its evidence
          and its full VersionStamp.

**Nothing here blocks an evaluation.** Every send goes through the outbox: a
row is written in the same transaction as the evaluation, and a worker drains
it — `delivery.py`, on `ai_core.outbox`. Until 2026-09-23 that sentence was a
promise with nothing behind it: there was no worker, only `POST /outbox/drain`,
and the platform's core loop closed only when somebody called it by hand. A
student's score must never depend on whether somebody else's service was up,
and this file is where that promise is either kept or quietly broken.

**Idempotency is M04's formula, not ours.** `observation_id()` reproduces
`uuid5(OBS_NAMESPACE, "{turn}|{concept}|{kind}|{rubric_version}")` exactly,
because M04 inserts on conflict-do-nothing. Derive it differently and a replay
stops being a no-op and starts being a second answer.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from ai_core.timeutil import utcnow

from .adapters import QuestionPackage
from .contracts import N_CATEGORIES, DimensionScore, Rubric, TurnEvaluation

log = logging.getLogger(__name__)

#: M04's namespace, copied verbatim from its `store.py`. If M04 ever changes
#: this, replays here silently become duplicates there — so it is asserted
#: against M04's published value in the contract tests rather than trusted.
OBS_NAMESPACE = uuid.UUID("6f1c1d3e-0000-4000-8000-000000000004")

#: M04 gates every write path on this header.
SERVICE_SECRET_HEADER = "X-Service-Secret"


def observation_id(
    *,
    turn_id: uuid.UUID | None,
    session_id: uuid.UUID,
    concept_id: str,
    kind: str,
    rubric_version: str,
) -> uuid.UUID:
    """M04's content hash, reproduced exactly (M04 §6.2, FR-4.25)."""
    anchor = turn_id or session_id
    return uuid.uuid5(OBS_NAMESPACE, f"{anchor}|{concept_id}|{kind}|{rubric_version}")


@dataclass(frozen=True)
class Observation:
    """The payload M04's `POST /v1/candidates/{id}/observations` takes.

    A dataclass rather than a dict so a missing field is a TypeError here
    instead of a 422 from a module that may not be running yet.
    """

    id: uuid.UUID
    candidate_id: uuid.UUID
    concept_id: str
    concept_weight: float
    session_id: uuid.UUID
    turn_id: uuid.UUID | None
    evidence: list[dict]
    kind: str
    response_model: str
    raw_category: int | None
    n_categories: int | None
    outcome: float
    item: dict | None
    source_dimension_key: str
    weight: float
    versions: dict
    consent_id: uuid.UUID
    observed_at: str

    def as_payload(self) -> dict:
        payload = {
            "candidate_id": str(self.candidate_id),
            "concept_id": self.concept_id,
            "concept_weight": self.concept_weight,
            "session_id": str(self.session_id),
            "turn_id": str(self.turn_id) if self.turn_id else None,
            "evidence": self.evidence,
            "kind": self.kind,
            "response_model": self.response_model,
            "raw_category": self.raw_category,
            "n_categories": self.n_categories,
            "outcome": self.outcome,
            "item": self.item,
            "source_dimension_key": self.source_dimension_key,
            "weight": self.weight,
            "versions": self.versions,
            "consent_id": str(self.consent_id),
            "observed_at": self.observed_at,
        }
        return payload


class NoConsent(ValueError):
    """M04 requires `consent_id` and has no default, so neither do we.

    Raised at build time rather than discovered as a 403 later: an evaluation
    without consent is one that cannot lawfully move a stored belief about a
    student, and the honest place to notice is before the row exists.
    """


def _hint_weight(hint_level: int) -> float:
    """M04 §6.3: hint-assisted answers take `weight × 0.7`, applied once, here."""
    return 0.7 if hint_level > 0 else 1.0


def observations_for(
    evaluation: TurnEvaluation,
    rubric: Rubric,
    package: QuestionPackage,
    communication_concepts: frozenset[str] = frozenset(),
) -> list[Observation]:
    """One observation per (turn, concept), from the concept-bearing dimension.

    The rule that stops communication quality becoming technical mastery
    (§6.1, AC-13.18). Two routes, and no third:

      * the ONE `concept_bearing` dimension  → the question's technical concepts
      * any `communication`-domain dimension → communication concepts only

    Which ids those are is M04's answer, passed in (`adapters.ConceptDomains`)
    rather than pattern-matched here. An empty set means M04 could not be
    asked, and then no communication observation is written at all — a score
    with nowhere true to go is not a belief about a student.

    A dimension that is neither produces nothing. That is deliberate: `depth`
    is a real score a student reads, and it is not a separate belief about a
    separate concept.
    """
    if evaluation.consent_id is None:
        raise NoConsent(
            "M04 requires consent_id on every observation and has no default. "
            "Consent is resolved at session start (M6), not at scoring time."
        )

    by_key = {s.dimension_key: s for s in evaluation.aggregated}
    out: list[Observation] = []

    bearing_key = rubric.concept_bearing_key
    bearing = by_key.get(bearing_key)
    if bearing is not None:
        technical = {
            cid: w
            for cid, w in package.concepts.items()
            if cid not in communication_concepts
        }
        out.extend(
            _build(evaluation, package, bearing, cid, weight, bearing_key)
            for cid, weight in sorted(technical.items())
        )

    for dimension in rubric.dimensions:
        if dimension.concept_domain != "communication":
            continue
        score = by_key.get(dimension.key)
        if score is None:
            continue
        comms = {
            cid: w for cid, w in package.concepts.items() if cid in communication_concepts
        }
        if not comms:
            # Nothing true to attach this to. The old fallback minted
            # `concept:communication`, which exists in no ontology: M04
            # rejected the whole batch as "unknown concept" and took the
            # turn's technical observation down with it, so a fully scored
            # interview moved nothing at all.
            continue
        out.extend(
            _build(evaluation, package, score, cid, weight, dimension.key)
            for cid, weight in sorted(comms.items())
        )

    return out


def _build(
    evaluation: TurnEvaluation,
    package: QuestionPackage,
    score: DimensionScore,
    concept_id: str,
    concept_weight: float,
    dimension_key: str,
) -> Observation:
    item = package.item
    return Observation(
        id=observation_id(
            turn_id=evaluation.turn_id,
            session_id=evaluation.session_id,
            concept_id=concept_id,
            kind="answer_scored",
            rubric_version=evaluation.versions.rubric_version or "none",
        ),
        candidate_id=evaluation.candidate_id,
        concept_id=concept_id,
        concept_weight=concept_weight,
        session_id=evaluation.session_id,
        turn_id=evaluation.turn_id,
        evidence=[ref.model_dump(mode="json") for ref in score.evidence],
        kind="answer_scored",
        # Rubric-scored ordinals are GRM's case, and it is the dominant one.
        # Without an item there is nothing to fit a likelihood against, so the
        # response model is `none` and M04 will not move theta (M04 §6.3).
        response_model="grm" if item is not None else "none",
        raw_category=score.raw_score,
        n_categories=N_CATEGORIES,
        # Display and BKT only — explicitly NOT the likelihood input.
        outcome=round(score.raw_score / (N_CATEGORIES - 1), 4),
        item=_item_payload(item),
        source_dimension_key=dimension_key,
        weight=_hint_weight(score.hint_level_used),
        versions=evaluation.versions.model_dump(mode="json"),
        consent_id=evaluation.consent_id,  # type: ignore[arg-type]
        observed_at=(evaluation.evaluated_at or utcnow()).isoformat(),
    )


def _item_payload(item: object | None) -> dict | None:
    if item is None:
        return None
    return {
        "question_id": str(getattr(item, "question_id", "")),
        "irt_model": getattr(item, "irt_model", "grm"),
        "a": getattr(item, "a", 1.0),
        "b": getattr(item, "b", 0.0),
        "params_source": getattr(item, "params_source", "prior"),
        "bank_version": getattr(item, "bank_version", "fixtures"),
    }


# ─────────────────────────────────────────────────────────────────────────
#  M19 — the Evidence Ledger (§6.4 step 8, M19 §6.1)
# ─────────────────────────────────────────────────────────────────────────


def ledger_entries(evaluation: TurnEvaluation) -> list[dict]:
    """One `dimension_score` entry per dimension, in M19's `LedgerEntry` shape.

    Append-only: a re-score inserts new entries and sets `supersedes` on the
    old, which is what makes "we re-scored under rubric v2.1" something the
    product can say out loud rather than something it hides.
    """
    return [
        {
            "candidate_id": str(evaluation.candidate_id),
            "session_id": str(evaluation.session_id),
            "turn_id": str(evaluation.turn_id),
            "claim_kind": "dimension_score",
            "claim_key": score.dimension_key,
            "value": float(score.raw_score),
            "evidence": [ref.model_dump(mode="json") for ref in score.evidence],
            "versions": evaluation.versions.model_dump(mode="json"),
            "computed_at": (evaluation.evaluated_at or utcnow()).isoformat(),
        }
        for score in evaluation.aggregated
    ]


# ─────────────────────────────────────────────────────────────────────────
#  M02 — the coverage ledger (M02 §6)
# ─────────────────────────────────────────────────────────────────────────


def coverage_update(evaluation: TurnEvaluation, rubric: Rubric) -> dict:
    """`asked` → `scored`, carrying the score M02 re-prioritises against.

    M02 §6: this transition is "the mechanism that makes coverage a guarantee
    rather than an intention". The score it takes is the concept-bearing one,
    for the same reason M04 does — a requirement is covered by whether the
    candidate could do the thing, not by how well they narrated it.

    `score` is on 0..1. M02 keeps one ledger across every rubric a session
    uses, and a bare category means nothing without the scale it came from —
    a 3 is strong on a five-level rubric and middling on a seven. The category
    and its scale travel beside it, so nothing is lost by normalising.
    """
    bearing = next(
        (s for s in evaluation.aggregated if s.dimension_key == rubric.concept_bearing_key),
        None,
    )
    return {
        "turn_id": str(evaluation.turn_id),
        "session_id": str(evaluation.session_id),
        "evaluation_id": str(evaluation.id),
        "state": "scored",
        "score": None if bearing is None else round(bearing.raw_score / (N_CATEGORIES - 1), 4),
        "raw_category": None if bearing is None else bearing.raw_score,
        "n_categories": N_CATEGORIES,
        "rubric_version": evaluation.versions.rubric_version,
        "scored_at": (evaluation.evaluated_at or utcnow()).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────────────────────────────────


def m04_base_url() -> str:
    return os.getenv("M04_BASE_URL", "http://127.0.0.1:8104").rstrip("/")


def observations_url(candidate_id: uuid.UUID) -> str:
    """M04's REAL path, checked against its router rather than assumed.

    An earlier draft of the spec invented `/v1/observations`; it does not
    exist. Getting this from the shipped code rather than from the plan is the
    difference between a merge and a debugging session.
    """
    return f"{m04_base_url()}/v1/candidates/{candidate_id}/observations"


def retest_url(candidate_id: uuid.UUID, concept_id: str) -> str:
    """M04 owns the retest_queue row; we ask for a dispute, it enqueues."""
    return f"{m04_base_url()}/v1/candidates/{candidate_id}/mastery/{concept_id}/dispute"


#: The name M04 reads (its `keys.SERVICE_SECRET_VAR`) and M15 sends. M13 read a
#: bare `SERVICE_SECRET`, so with the platform's documented variable set, every
#: observation still went out unauthenticated. The old name is still read, so a
#: keys.txt written against it keeps working.
SERVICE_SECRET_VARS = ("M04_SERVICE_SECRET", "SERVICE_SECRET")


def service_headers() -> dict[str, str]:
    for name in SERVICE_SECRET_VARS:
        secret = os.getenv(name, "").strip()
        if secret:
            return {SERVICE_SECRET_HEADER: secret}
    return {}


def coverage_url(session_id: object, candidate_id: object, turn_id: object) -> str | None:
    """M02's turn-scoped score route, or None when no M02 is configured.

    None is not an error. M02 is optional to M13 like every upstream is, and a
    session that never came from a job description has no ledger to move.
    """
    from .dependencies import deps  # noqa: PLC0415 - avoids an import cycle via router

    dep = deps().get("M02")
    if dep is None or not dep.base_url:
        return None
    return (
        # M02's own noun since 2026-10-02 — `sessions` is M05's in the shell.
        f"{dep.base_url.rstrip('/')}/v1/coverage/{session_id}/{candidate_id}"
        f"/turns/{turn_id}/score"
    )


__all__ = [
    "OBS_NAMESPACE",
    "SERVICE_SECRET_HEADER",
    "SERVICE_SECRET_VARS",
    "NoConsent",
    "Observation",
    "coverage_update",
    "coverage_url",
    "ledger_entries",
    "m04_base_url",
    "observation_id",
    "observations_for",
    "observations_url",
    "retest_url",
    "service_headers",
]

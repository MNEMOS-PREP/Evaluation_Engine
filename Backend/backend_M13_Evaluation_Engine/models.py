"""Storage — the rows this module owns.

Everything here is append-only or append-mostly, because the module's whole
argument is that a number can be explained later. A re-score inserts and
points back (`superseded_by`); it never overwrites. A dispute resolution
appends a correction; the original stays.

Four tables and one queue:

``m13_evaluation``      one row per scored turn, with its evidence and versions.
``m13_observation_outbox``
                        observations bound for M04, held here until they are
                        acknowledged. The outbox exists so a student's
                        evaluation never fails because a downstream module is
                        down (§6.11) — and so a replay cannot double-count,
                        because the id is a content hash M04 also derives.
``m13_human_rating``    the calibration study's raw data, carrying all three
                        MFRM facets (§6.6).
``m13_calibration``     a fitted mapping per (dimension, round_type,
                        ensemble_config). The display gate reads this and
                        nothing else (§6.7).
``m13_dispute``         a student's challenge, its review state, and what came
                        of it (§2.3).

SQLite by default, Postgres when `DATABASE_URL` is set — both through
`ai_core.db`, and `ai_core.schema_repair` adds columns additively on startup so
a pulled model change does not cost anyone their local data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from ai_core.timeutil import utcnow
from sqlalchemy import JSON as SAJSON
from sqlalchemy import Column, Index
from sqlmodel import Field, SQLModel


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class OutboxState(StrEnum):
    pending = "pending"
    sent = "sent"
    #: Permanently rejected by M04 — a 4xx that a replay cannot fix. Kept
    #: rather than deleted, because "the mastery map is missing this answer"
    #: is a question someone will ask.
    rejected = "rejected"


class DisputeState(StrEnum):
    open = "open"
    upheld = "upheld"
    rejected = "rejected"


class Evaluation(SQLModel, table=True):
    """One scored turn. The `payload` is the full `TurnEvaluation`.

    The typed columns beside it are the ones we query on — a JSON blob you
    cannot filter is an archive, not a table.
    """

    __tablename__ = "m13_evaluation"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    turn_id: uuid.UUID = Field(index=True)
    candidate_id: uuid.UUID = Field(index=True)
    session_id: uuid.UUID = Field(index=True)
    rubric_id: uuid.UUID
    rubric_version: str
    #: Needed to resolve the question package when replaying the outbound
    #: contract — `TurnEvaluation` deliberately does not carry it, because the
    #: evaluator must never see anything that identifies the item's source.
    question_id: uuid.UUID | None = Field(default=None, index=True)
    round_type: str = Field(default="", index=True)
    ensemble_config: str
    #: `calibration` or `dev` — the corpus is assembled by filtering on this,
    #: which is the whole reason it is a column and not a note (§11).
    score_grade: str = Field(default="dev", index=True)
    status: str = Field(default="complete", index=True)
    scaffold_used: bool = False
    payload: dict = Field(default_factory=dict, sa_column=Column(SAJSON))
    evaluated_at: datetime = Field(default_factory=utcnow, index=True)
    #: A re-score appends and points the old row here. Never an overwrite.
    superseded_by: uuid.UUID | None = Field(default=None, index=True)


class ObservationOutbox(SQLModel, table=True):
    """An observation bound for M04, and whether it got there.

    The id is M04's own content hash, not a fresh uuid4. That is what makes a
    replay safe: M04 inserts on conflict-do-nothing, so sending the same row
    twice is a no-op rather than a double-counted answer.
    """

    __tablename__ = "m13_observation_outbox"

    #: Surrogate. NOT M04's id — a re-score under the same rubric produces the
    #: SAME observation id, and the retraction of the old one and the new one
    #: have to be able to sit in this table at the same time.
    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    #: M04's content hash. What actually goes on the wire, and what M04
    #: deduplicates on.
    observation_id: uuid.UUID = Field(index=True)
    evaluation_id: uuid.UUID = Field(index=True)
    candidate_id: uuid.UUID = Field(index=True)
    concept_id: str = Field(index=True)
    kind: str = "answer_scored"
    state: str = Field(default=OutboxState.pending, index=True)
    attempts: int = 0
    last_error: str | None = None
    payload: dict = Field(default_factory=dict, sa_column=Column(SAJSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    sent_at: datetime | None = None


class HumanRating(SQLModel, table=True):
    """The calibration study's raw data — §6.6.

    Carries all three MFRM facets. The previous shape had one, which made the
    analysis §6.6 calls its headline unfittable from its own table.
    """

    __tablename__ = "m13_human_rating"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    turn_id: uuid.UUID = Field(index=True)
    question_id: uuid.UUID = Field(index=True)  # the ITEM facet
    candidate_id: uuid.UUID = Field(index=True)  # the PERSON facet
    rater_id: str = Field(index=True)  # the RATER facet
    dimension_key: str = Field(index=True)
    round_type: str = Field(index=True)
    rubric_version: str = Field(index=True)
    score: int
    rater_confidence: int | None = None
    time_spent_s: int = 0
    is_gold: bool = False
    #: "can't judge". Forcing a rating on an ambiguous item is how you get
    #: noise, so this is a first-class outcome rather than a missing row.
    skipped: bool = False
    consent_id: uuid.UUID | None = None
    purpose: str = Field(default="research", index=True)
    rated_at: datetime = Field(default_factory=utcnow, index=True)


class Calibration(SQLModel, table=True):
    """A fitted mapping, and the metrics that decide whether it may be shown.

    Keyed on `ensemble_config` as well as dimension and round type: a median
    of three is a different estimator from a single draw, and a mapping fitted
    on one does not describe the other (Trap 10).
    """

    __tablename__ = "m13_calibration"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    dimension_key: str = Field(index=True)
    round_type: str = Field(index=True)
    ensemble_config: str = Field(index=True)
    method: str = "identity"
    params: dict = Field(default_factory=dict, sa_column=Column(SAJSON))
    fitted_on_n: int = 0
    scaffold_stratum: str = "pooled"
    qwk: float = 0.0
    qwk_overall: float = 0.0
    krippendorff_alpha: float = 0.0
    ece: float = 1.0
    #: Score LEVELS per natural-log unit of answer length. Gate: |beta| < 0.15.
    length_bias_beta: float = 0.0
    subgroup_report: dict = Field(default_factory=dict, sa_column=Column(SAJSON))
    #: Denormalised so the render path is one read. Recomputed on every fit.
    display_numeric: bool = False
    gate_reasons: dict = Field(default_factory=dict, sa_column=Column(SAJSON))
    dataset_version: str = "v1"
    fitted_at: datetime = Field(default_factory=utcnow, index=True)
    superseded_by: uuid.UUID | None = Field(default=None, index=True)


class Dispute(SQLModel, table=True):
    """A student saying the score is wrong — §2.3.

    `retest_requested` is the half that matters. The review resolves the
    argument; the re-test resolves it with data, and it happens either way.
    """

    __tablename__ = "m13_dispute"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    evaluation_id: uuid.UUID = Field(index=True)
    candidate_id: uuid.UUID = Field(index=True)
    dimension_key: str | None = None
    reason: str
    note: str = ""
    state: str = Field(default=DisputeState.open, index=True)
    retest_requested: bool = False
    retest_error: str | None = None
    resolution_note: str = ""
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    resolved_at: datetime | None = None


Index("ix_m13_eval_live", Evaluation.candidate_id, Evaluation.evaluated_at)
Index("ix_m13_outbox_pending", ObservationOutbox.state, ObservationOutbox.created_at)


__all__ = [
    "Calibration",
    "Dispute",
    "DisputeState",
    "Evaluation",
    "HumanRating",
    "ObservationOutbox",
    "OutboxState",
]

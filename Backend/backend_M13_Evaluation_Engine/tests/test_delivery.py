"""The worker `emit.py` promised, and the two things it delivers.

The failure this file exists for: on 2026-09-20 the platform's core loop closed
for the first time — and only because somebody called `POST /v1/outbox/drain`
by hand. There was no worker. Every test below is about delivery happening
without anybody pressing anything, or about a row that cannot be delivered
being visible rather than silent.

No socket is opened. The wire is `delivery.post_json`, replaced by `Wire`.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from ai_core import outbox as core_outbox
from ai_core.outbox import Outcome, Sweeper
from sqlmodel import Session, select

from backend_M13_Evaluation_Engine import app as app_module
from backend_M13_Evaluation_Engine import delivery, emit, store
from backend_M13_Evaluation_Engine import llm as llm_module
from backend_M13_Evaluation_Engine.models import CoverageOutbox, ObservationOutbox
from backend_M13_Evaluation_Engine.service import TurnInput, evaluate_turn, outbound

from .conftest import StubLLM


class Wire:
    """Stands in for the network: records every request, answers from a script."""

    def __init__(self, outcome: Outcome | None = None):
        self.outcome = outcome or Outcome.sent("http_201")
        self.calls: list[dict] = []

    def __call__(self, url, payload, *, headers=None, timeout=10.0, method="POST"):
        self.calls.append({"url": url, "payload": payload, "headers": dict(headers or {})})
        return self.outcome

    def to(self, fragment: str) -> list[dict]:
        return [c for c in self.calls if fragment in c["url"]]


@pytest.fixture(name="wire")
def wire_fixture(monkeypatch) -> Wire:
    wire = Wire()
    monkeypatch.setattr(delivery, "post_json", wire)
    return wire


@pytest.fixture(name="saved")
def saved_fixture(session, questions, cases, rubric):
    package = questions.by_label("hashmap_lookup_why")
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=cases["hashmap_full_credit"].answer_text,
        consent_id=uuid.uuid4(),
    )
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"), question=package)
    store.save_evaluation(session, evaluation, outbound(evaluation, rubric, package))
    return evaluation


def _sweeper(engine) -> Sweeper:
    return Sweeper("M13-test", lambda: Session(engine), delivery.channels, interval_s=0)


def _rows(session, model):
    session.expire_all()
    return list(session.exec(select(model)).all())


# ─────────────────────────────────────────────────────────────────────────
#  What an evaluation owes
# ─────────────────────────────────────────────────────────────────────────


def test_a_scored_turn_owes_m02_its_score(session, saved):
    """M02 §6.6: the `scored` transition is what makes coverage a guarantee.
    It was assembled by `emit.coverage_update` and never queued anywhere."""
    (row,) = _rows(session, CoverageOutbox)

    assert row.turn_id == saved.turn_id
    assert row.evaluation_id == saved.id
    assert 0.0 <= row.payload["score"] <= 1.0
    assert row.state == core_outbox.PENDING


def test_without_an_m02_nothing_is_owed_to_it(session, questions, cases, rubric, monkeypatch):
    """A queue for a module this deployment does not run is owed for ever."""
    monkeypatch.setattr(emit, "coverage_url", lambda *a: None)
    package = questions.by_label("hashmap_lookup_why")
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=cases["hashmap_full_credit"].answer_text,
        consent_id=uuid.uuid4(),
    )
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"), question=package)
    store.save_evaluation(session, evaluation, outbound(evaluation, rubric, package))

    assert _rows(session, CoverageOutbox) == []
    assert _rows(session, ObservationOutbox), "M04 is still owed its observations"


# ─────────────────────────────────────────────────────────────────────────
#  Delivered without anybody pressing anything
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.gate
def test_one_sweep_delivers_everything_owed(engine, session, saved, wire):
    """The gate for the promise in `emit.py`: nobody calls drain."""
    _sweeper(engine).sweep_once()

    assert {r.state for r in _rows(session, ObservationOutbox)} == {core_outbox.SENT}
    assert {r.state for r in _rows(session, CoverageOutbox)} == {core_outbox.SENT}

    (m04,) = wire.to("/observations")
    assert m04["url"].endswith(f"/v1/candidates/{saved.candidate_id}/observations")
    assert len(m04["payload"]["observations"]) >= 1, "one batched call per candidate"

    (m02,) = wire.to("/coverage/")
    assert m02["url"].endswith(
        f"/v1/coverage/{saved.session_id}/{saved.candidate_id}/turns/{saved.turn_id}/score"
    )
    assert m02["payload"]["evaluation_id"] == str(saved.id)


def test_the_ledger_write_is_made_as_the_student(engine, saved, wire):
    """M02's ledger is candidate-scoped and guarded. M13 forwards the student,
    exactly as M06 does when it writes the same ledger — no service role."""
    _sweeper(engine).sweep_once()

    (m02,) = wire.to("/coverage/")
    assert m02["headers"] == {"X-Role": "student", "X-Candidate-Id": str(saved.candidate_id)}


def test_observations_carry_the_secret_under_the_platforms_name(engine, saved, wire, monkeypatch):
    """M04 reads `M04_SERVICE_SECRET`. M13 read `SERVICE_SECRET`, so with the
    documented variable set every observation still went unauthenticated."""
    monkeypatch.delenv("SERVICE_SECRET", raising=False)
    monkeypatch.setenv("M04_SERVICE_SECRET", "shared-with-m04")

    _sweeper(engine).sweep_once()

    (m04,) = wire.to("/observations")
    assert m04["headers"]["X-Service-Secret"] == "shared-with-m04"


def test_observations_are_written_as_the_student_not_just_the_service(engine, saved, wire):
    """M04 guards every candidate route on who the request is FOR. The secret
    says M13 is calling; without the student, M04 answers 403 and no scored
    answer moves the skill graph."""
    _sweeper(engine).sweep_once()

    (m04,) = wire.to("/observations")
    assert m04["headers"]["X-Role"] == "student"
    assert m04["headers"]["X-Candidate-Id"] == str(saved.candidate_id)


def test_m04_down_all_afternoon_holds_nothing(engine, session, saved, wire):
    """An outage is not the row's fault. When M04 comes back, the rows go —
    without a person noticing and requeueing them."""
    wire.outcome = Outcome.unreachable("ConnectionRefusedError")
    for _ in range(core_outbox.RetryPolicy().max_failures * 2):
        for row in _rows(session, ObservationOutbox) + _rows(session, CoverageOutbox):
            row.next_attempt_at = None
            session.add(row)
        session.commit()
        _sweeper(engine).sweep_once()

    rows = _rows(session, ObservationOutbox)
    assert {r.state for r in rows} == {core_outbox.PENDING}
    assert all(r.failures == 0 for r in rows)

    wire.outcome = Outcome.sent("http_201")
    for row in rows:
        row.next_attempt_at = None
        session.add(row)
    session.commit()
    _sweeper(engine).sweep_once()
    assert {r.state for r in _rows(session, ObservationOutbox)} == {core_outbox.SENT}


@pytest.mark.gate
def test_an_evaluation_kicks_the_worker(client, cases, monkeypatch):
    """Delivery in milliseconds, not at the next interval. Checked at the call
    site: deleting the `kick()` in the route must fail this, not just a unit
    test of `kick` itself."""
    kicks = []
    monkeypatch.setattr(delivery, "kick", lambda: kicks.append(1))
    llm_module.set_llm(StubLLM("honest"))

    response = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": cases["hashmap_full_credit"].answer_text,
        },
    )

    assert response.status_code == 200
    assert kicks == [1]


@pytest.mark.gate
def test_the_app_runs_the_worker_for_its_whole_life(monkeypatch):
    """The lifespan is the call site. A sweeper that exists and is never
    started is `emit.py`'s docstring again."""
    entered: list[str] = []

    class Spy:
        @contextlib.contextmanager
        def running(self):
            entered.append("start")
            yield None
            entered.append("stop")

    monkeypatch.setattr(delivery, "sweeper", lambda: Spy())
    monkeypatch.setattr(app_module, "load_keys", lambda: [])
    monkeypatch.setattr(app_module, "create_all", lambda: None)
    monkeypatch.setattr(app_module, "ensure_schema", lambda _engine: [])

    async def boot():
        async with app_module.lifespan(app_module.app):
            assert entered == ["start"]

    asyncio.run(boot())
    assert entered == ["start", "stop"]


# ─────────────────────────────────────────────────────────────────────────
#  Nothing stuck is invisible
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.gate
def test_a_rejected_row_is_on_the_outbox_page_with_its_reason(client, session, saved):
    """It used to vanish: `pending: 0`, `items: []`, and the reason only in
    the database. A row nobody can see is a row nobody fixes."""
    store.drain(session, sender=lambda c, o: (False, "http_422: unknown concept"))

    body = client.get("/v1/outbox").json()
    m04 = body["channels"]["m04.observations"]

    assert m04["stuck"] >= 1
    assert m04["stuck_rows"][0]["last_error"] == "http_422: unknown concept"
    assert m04["stuck_rows"][0]["concept_id"]
    assert body["pending"] == 0  # the old field, still true, no longer the whole story


def test_requeue_puts_stuck_rows_back_after_the_fix(client, session, saved):
    store.drain(session, sender=lambda c, o: (False, "http_422: unknown concept"))

    body = client.post("/v1/outbox/requeue").json()

    assert body["requeued"]["m04.observations"] >= 1
    assert store.pending_observations(session)


def test_a_rescore_before_sending_is_void_not_stuck(session, saved, questions, cases, rubric):
    """Superseded before it went is nothing wrong. Marking it `rejected` would
    list it as needing a person."""
    package = questions.by_label("hashmap_lookup_why")
    turn = TurnInput(
        turn_id=saved.turn_id,
        candidate_id=saved.candidate_id,
        session_id=saved.session_id,
        question_id=package.question_id,
        answer_text=cases["hashmap_full_credit"].answer_text,
        consent_id=uuid.uuid4(),
    )
    rescored = evaluate_turn(turn, llm=StubLLM("honest"), question=package)
    store.save_evaluation(session, rescored, outbound(rescored, rubric, package))
    store.supersede(session, saved.id, rescored.id)

    old = [r for r in _rows(session, CoverageOutbox) if r.evaluation_id == saved.id]
    assert {r.state for r in old} == {core_outbox.VOID}
    assert core_outbox.summary(session, ObservationOutbox)["stuck"] == 0
    assert core_outbox.summary(session, CoverageOutbox)["stuck"] == 0

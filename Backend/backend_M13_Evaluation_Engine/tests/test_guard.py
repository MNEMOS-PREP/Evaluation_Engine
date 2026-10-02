"""Who may ask — Platform_Core v0.11.0's guard on M13's router.

Until 2026-10-02 M13 checked nobody: a student's evaluation, its evidence
spans and the exact request M13 sent its evaluators answered to anyone holding
a turn id, and anyone could have a turn scored in another student's name.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from ai_core.db import get_session
from ai_core.guard import identity_headers
from ai_core.testing import OWNER, assert_refuses_strangers
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend_M13_Evaluation_Engine import llm as llm_module

from .conftest import StubLLM

STRANGER = str(uuid.uuid4())


@pytest.fixture(name="bare")
def bare_fixture(session: Session) -> Iterator[TestClient]:
    from backend_M13_Evaluation_Engine.app import app

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _score_for(client: TestClient, candidate: str, turn: str, cases) -> dict:
    llm_module.set_llm(StubLLM("honest"))
    response = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": cases["hashmap_full_credit"].answer_text,
            "candidate_id": candidate,
            "turn_id": turn,
        },
        headers=identity_headers(candidate),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_every_route_about_an_evaluation_refuses_strangers(bare, cases):
    """An evaluation whose turn id is the shared check's OWNER, for OWNER, so
    the `{turn_id}` routes resolve to a real student."""
    from backend_M13_Evaluation_Engine.app import app

    _score_for(bare, OWNER, OWNER, cases)
    checked = assert_refuses_strangers(bare, app, params=("candidate_id", "turn_id"))
    assert ("GET", "/v1/evaluations/{turn_id}/evidence") in checked


def test_the_student_reads_their_own_and_nobody_elses(bare, cases):
    mine = str(uuid.uuid4())
    turn = str(uuid.uuid4())
    _score_for(bare, mine, turn, cases)
    assert bare.get(f"/v1/evaluations/{turn}", headers=identity_headers(mine)).status_code == 200
    assert (
        bare.get(f"/v1/evaluations/{turn}", headers=identity_headers(STRANGER)).status_code == 403
    )
    assert bare.get(f"/v1/evaluations/{turn}").status_code == 403


def test_nobody_has_a_turn_scored_in_somebody_elses_name(bare, cases):
    llm_module.set_llm(StubLLM("honest"))
    response = bare.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": "hi",
            "candidate_id": str(uuid.uuid4()),
        },
        headers=identity_headers(STRANGER),
    )
    assert response.status_code == 403


def test_a_dispute_is_the_students_own(bare, cases):
    mine = str(uuid.uuid4())
    evaluation = _score_for(bare, mine, str(uuid.uuid4()), cases)
    url = f"/v1/evaluations/{evaluation['id']}/dispute"
    body = {"reason": "the quote is not what I said", "dimension_key": "correctness"}
    assert bare.post(url, json=body, headers=identity_headers(STRANGER)).status_code == 403

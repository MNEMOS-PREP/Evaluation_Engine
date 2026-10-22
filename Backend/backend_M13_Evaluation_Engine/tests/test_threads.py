"""2026-10-22: one question's answers, scored together — and the checklist
that told correct answers they had missed everything.

M06 now sends one evaluation per QUESTION: every answer the student gave to
it, in order (never the interviewer's words), with the key points of what was
actually asked and the corrective prompts a correction needed.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M13_Evaluation_Engine import llm as llm_module
from backend_M13_Evaluation_Engine.contracts import DimensionScore
from backend_M13_Evaluation_Engine.coverage import LexicalCoverage, score
from backend_M13_Evaluation_Engine.service import TurnInput, apply_hint_credit, evaluate_turn

from .conftest import StubLLM

#: A correct answer to "why is average hash map lookup O(1)", in the
#: student's own words — almost none of the key points' words.
PARAPHRASE = (
    "You compute a hash of the key and jump straight to that slot, so no search. It stays "
    "fast while entries are spread evenly and the table is resized before it gets too full; "
    "if everything collides it becomes linear."
)


def test_an_empty_checklist_from_the_evaluators_is_their_judgement(questions):
    """The bug: an empty list was refilled from the word-overlap measure, and
    this answer — complete, in other words — was told it missed every point."""
    package = questions.by_label("hashmap_lookup_why")
    lexical = score(PARAPHRASE, package.key_points, model=LexicalCoverage())
    assert lexical.missing(), "the word-overlap measure does flag it — that was the trap"

    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=PARAPHRASE,
    )
    evaluation = evaluate_turn(turn, llm=StubLLM("honest", score=4), question=package)
    assert evaluation.aggregated
    for dimension in evaluation.aggregated:
        assert dimension.missing_key_points == [], dimension.dimension_key


def test_help_toward_a_correction_is_priced_like_a_hint(rubric):
    scores = [DimensionScore(dimension_key="correctness", raw_score=4)]
    apply_hint_credit(scores, rubric, hint_level=1)
    assert scores[0].credited_score == pytest.approx(4 * rubric.credit(1))


def test_help_beyond_the_table_keeps_the_last_price_not_full_credit(rubric):
    top = max(rubric.hint_penalty)
    scores = [DimensionScore(dimension_key="correctness", raw_score=4)]
    apply_hint_credit(scores, rubric, hint_level=top + 3)
    assert scores[0].credited_score == pytest.approx(4 * rubric.credit(top))
    assert scores[0].credited_score < 4


def test_prompts_reach_the_credit_through_the_route(client, questions):
    llm_module.set_llm(StubLLM("honest", score=4))
    body = {
        "question_label": "hashmap_lookup_why",
        "answer_text": PARAPHRASE,
    }
    plain = client.post("/v1/evaluations", json=body).json()
    helped = client.post("/v1/evaluations", json={**body, "prompts_used": 2}).json()
    plain_score = {s["dimension_key"]: s["credited_score"] for s in plain["aggregated"]}
    helped_score = {s["dimension_key"]: s["credited_score"] for s in helped["aggregated"]}
    assert all(helped_score[k] < plain_score[k] for k in plain_score)


def test_only_what_was_asked_is_what_the_answer_is_judged_against(client, questions):
    package = questions.by_label("hashmap_lookup_why")
    first, *rest = package.key_points
    assert rest, "the fixture has more than one key point"
    stub = StubLLM("honest")
    llm_module.set_llm(stub)
    response = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": PARAPHRASE,
            "key_point_ids": [first.id],
        },
    )
    assert response.status_code == 200
    prompt = stub.calls[0]["user"]
    assert first.statement in prompt
    assert all(kp.statement not in prompt for kp in rest)


def test_a_scope_that_names_nothing_known_judges_against_everything(client, questions):
    package = questions.by_label("hashmap_lookup_why")
    stub = StubLLM("honest")
    llm_module.set_llm(stub)
    client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": PARAPHRASE,
            "key_point_ids": ["no-such-point"],
        },
    )
    prompt = stub.calls[0]["user"]
    assert all(kp.statement in prompt for kp in package.key_points)


def test_the_evaluator_is_told_how_to_read_several_answers():
    from backend_M13_Evaluation_Engine.evaluator import SYSTEM_PROMPT
    from backend_M13_Evaluation_Engine.schemas import PROMPT_VERSION

    assert "SEVERAL answers to the same question" in SYSTEM_PROMPT
    assert PROMPT_VERSION == "m13-eval-1.1.0"

"""The live M05 question source, against a patched `urlopen` — no socket.

Before this existed, `get_questions()` was always the fixture bank: every real
M05 question id answered 404 and nothing from the live bank could be scored.
These are the properties that keep it honest — M05 builds the package, the
fixture bank stays reachable behind it, and an M05 that is down or odd
degrades rather than failing.
"""

from __future__ import annotations

import io
import json
import urllib.error
import uuid

import pytest

from backend_M13_Evaluation_Engine import adapters
from backend_M13_Evaluation_Engine.adapters import (
    FixtureQuestions,
    LiveQuestions,
    QuestionPackage,
)

PACKAGE = {
    "question_id": "11111111-2222-4333-8444-555555555555",
    "stem": "You have a single loop over an array of n elements. What is the time complexity?",
    "reference_answer": "O(n): constant work, n times.",
    "key_points": [
        {"id": "kp1", "statement": "States the complexity is linear in n.", "required": True},
        {
            "id": "kp2",
            "statement": "Justifies it by constant work repeated n times.",
            "weight": 0.5,
        },
    ],
    "round_type": "dsa_verbal",
    "concepts": {"concept:time_complexity": 1.0},
    "item": {
        "question_id": "11111111-2222-4333-8444-555555555555",
        "irt_model": "grm",
        "a": 1.2,
        "b": [-0.5, 0.2, 0.9],
        "params_source": "prior",
        "bank_version": "seed",
    },
    "label": "loop_complexity",
}

QUESTION_ID = uuid.UUID(PACKAGE["question_id"])


class Wire:
    """Answers each path from a table; records what was asked."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.asked: list[str] = []
        self.secrets: list[str | None] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        self.secrets.append(request.get_header("X-service-secret"))
        for fragment, response in self.routes.items():
            if fragment in url:
                if isinstance(response, int):
                    raise urllib.error.HTTPError(url, response, "err", {}, io.BytesIO(b"{}"))
                if isinstance(response, Exception):
                    raise response
                return _Resp(response)
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b"{}"))


class _Resp:
    def __init__(self, body):
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wire(monkeypatch):
    def install(routes: dict[str, object]) -> Wire:
        recorder = Wire(routes)
        monkeypatch.setattr(adapters.urllib.request, "urlopen", recorder)
        return recorder

    return install


def test_a_real_m05_item_becomes_a_package(wire):
    recorder = wire({"/package": PACKAGE})
    package = LiveQuestions("http://m05").get(QUESTION_ID, "dsa_verbal")
    assert isinstance(package, QuestionPackage)
    assert package.question_id == QUESTION_ID
    assert [kp.id for kp in package.key_points] == ["kp1", "kp2"]
    assert package.key_points[0].required is True
    assert package.concepts == {"concept:time_complexity": 1.0}
    assert "round_type=dsa_verbal" in recorder.asked[0]


def test_the_administered_round_type_is_what_is_asked_for(wire):
    """An item eligible in two round types has two packages."""
    recorder = wire({"/package": {**PACKAGE, "round_type": "cs_core"}})
    package = LiveQuestions("http://m05").get(QUESTION_ID, "cs_core")
    assert package is not None and package.round_type == "cs_core"
    assert "round_type=cs_core" in recorder.asked[0]


def test_item_parameters_decide_theta_eligibility(wire):
    wire({"/package": PACKAGE})
    eligible = LiveQuestions("http://m05").get(QUESTION_ID, "dsa_verbal")
    assert eligible is not None and eligible.theta_eligible is True
    assert eligible.item is not None and eligible.item.a == 1.2

    wire({"/package": {**PACKAGE, "item": None}})
    grounded = LiveQuestions("http://m05").get(QUESTION_ID, "dsa_verbal")
    assert grounded is not None and grounded.theta_eligible is False


def test_an_unknown_round_type_is_looked_up_on_the_item(wire):
    recorder = wire(
        {
            f"/v1/questions/{QUESTION_ID}/package": PACKAGE,
            f"/v1/questions/{QUESTION_ID}": {
                "id": str(QUESTION_ID),
                "rubric_round_type": "dsa_verbal",
                "round_types": ["dsa_verbal"],
            },
        }
    )
    package = LiveQuestions("http://m05").get(QUESTION_ID)
    assert package is not None
    # The item first, then its package — and only because nobody said.
    assert recorder.asked[0].endswith(str(QUESTION_ID))
    assert "round_type=dsa_verbal" in recorder.asked[1]


def test_the_fixture_bank_stays_reachable_behind_m05(wire):
    """The regression suite and `question_label` address fixture ids."""
    fixture = FixtureQuestions().all()[0]
    wire({"/package": 404})
    live = LiveQuestions("http://m05")
    assert live.get(fixture.question_id, fixture.round_type) == fixture
    assert live.by_label(fixture.label) == fixture
    assert live.all() == FixtureQuestions().all()


@pytest.mark.parametrize(
    "response",
    [404, 422, 500, urllib.error.URLError("refused"), TimeoutError("slow")],
)
def test_every_kind_of_m05_trouble_degrades_to_the_fixture_bank(wire, response):
    wire({"/v1/questions": response})
    assert LiveQuestions("http://m05").get(uuid.uuid4(), "dsa_verbal") is None


def test_a_malformed_package_is_refused_rather_than_half_used(wire):
    wire({"/package": {"question_id": str(QUESTION_ID), "round_type": "dsa_verbal"}})
    assert LiveQuestions("http://m05").get(QUESTION_ID, "dsa_verbal") is None


@pytest.mark.gate
def test_scoring_a_live_m05_turn_end_to_end(client, wire):
    """The Phase-1 gate in miniature: a real question id, scored.

    This is the request M06 makes for every answered turn. Before the live
    source existed it was a 404 for every id M05 owns.
    """
    wire({"/package": PACKAGE})
    adapters.set_questions(LiveQuestions("http://m05"))
    try:
        response = client.post(
            "/v1/evaluations",
            json={
                "turn_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "question_id": str(QUESTION_ID),
                "answer_text": "It is O(n): the body does constant work and runs once per element.",
                "round_type": "dsa_verbal",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["turn_id"]
        # No key was configured, so the honest outcome is a review flag rather
        # than a fabricated score — and it got that far, which is the point.
        assert body["status"] in ("complete", "needs_human_review")
    finally:
        adapters.set_questions(None)


def test_m05_is_asked_as_a_module(wire):
    """M05 serves the answer key only to a caller holding the platform secret
    (Platform_Core v0.12.0). Asked without it, `/package` is a 401, and every
    live item would silently fall through to the fixture bank and then 404."""
    from ai_core import service

    recorder = wire(
        {"/package": PACKAGE, f"/v1/questions/{QUESTION_ID}": {"round_types": ["dsa_verbal"]}}
    )
    LiveQuestions("http://m05").get(QUESTION_ID, None)
    assert len(recorder.asked) == 2
    assert recorder.secrets == [service.secret(), service.secret()]

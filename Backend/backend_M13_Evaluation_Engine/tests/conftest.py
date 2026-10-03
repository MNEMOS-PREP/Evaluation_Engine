"""Shared fixtures for M13 tests.

**No test in this repo opens a socket.** Not as a convenience — as a property:
`llm.get_llm()` returns `NullLLM` without a key, so a test that accidentally
reached the network would be exercising a path the module treats as optional
and would fail on a marker's laptop. `StubLLM` is the injection point, and it
is deliberately capable of being *dishonest*, because the evidence gate is
only meaningful if something in the suite tries to get past it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

# Before anything imports `delivery`: the `client` fixture enters the app's
# lifespan, and a running sweeper there would drain the developer's real
# dev.db and open sockets to M04 and M02 on every kick. The worker is tested
# directly (`test_delivery.py`), against this suite's own engine.
os.environ["M13_OUTBOX_SWEEP_S"] = "0"

import pytest
from ai_core.db import get_session
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend_M13_Evaluation_Engine import llm as llm_module
from backend_M13_Evaluation_Engine import rubrics
from backend_M13_Evaluation_Engine.adapters import FixtureQuestions, regression_cases
from backend_M13_Evaluation_Engine.evidence import Artifact, ArtifactSet
from backend_M13_Evaluation_Engine.llm import LLMResult
from backend_M13_Evaluation_Engine.projection import project_for_evaluator
from backend_M13_Evaluation_Engine.service import TurnInput


class StubLLM:
    """An evaluator that is not one.

    Four modes, and each exists to test one thing:

    ``honest``      quotes real text at real offsets — the happy path.
    ``drifted``     quotes real text at WRONG offsets — exercises repair.
    ``paraphrase``  quotes text that is *nearly* right — must be rejected or
                    repaired-and-overwritten, never stored as given.
    ``fabricated``  quotes text that is not in the artifact at all — must be
                    rejected on both attempts and the evaluator dropped.
    """

    name = "stub"

    def __init__(self, mode: str = "honest", *, score: int = 3, quote_len: int = 40):
        self.mode = mode
        self.score = score
        self.quote_len = quote_len
        self.calls: list[dict] = []

    def structured(self, *, job, system, user, schema, max_tokens=8000):
        self.calls.append({"job": job, "system": system, "user": user, "schema": schema})

        answer = _artifact_text_from_prompt(user)
        dimension_keys = _dimension_keys_from_schema(schema)
        artifact_id = _artifact_id_from_schema(schema)

        scores = [
            {
                "dimension_key": key,
                "raw_score": self.score,
                "reasoning": f"stub reasoning for {key}",
                "evidence": [self._span(answer, artifact_id)],
                "missing_key_points": [],
                "model_confidence": 0.8,
            }
            for key in dimension_keys
        ]

        return LLMResult(
            ok=True,
            data={"scores": scores, "overall_note": "stub", "disqualifiers_triggered": []},
            model="stub-model",
            job=job,
            tokens_in=1200,
            tokens_out=400,
            cached_in=900,
            latency_ms=5,
        )

    def _span(self, answer: str, artifact_id: str) -> dict:
        start = 0
        end = min(self.quote_len, len(answer))
        quote = answer[start:end]

        if self.mode == "honest":
            return {"artifact_id": artifact_id, "start": start, "end": end, "quote": quote}
        if self.mode == "drifted":
            # Real text, wrong offsets — exactly the case repair exists for.
            return {"artifact_id": artifact_id, "start": start + 7, "end": end + 7, "quote": quote}
        if self.mode == "paraphrase":
            mangled = quote.replace("a", "@", 1) if "a" in quote else quote[:-3] + "xyz"
            return {"artifact_id": artifact_id, "start": start, "end": end, "quote": mangled}
        return {
            "artifact_id": artifact_id,
            "start": 0,
            "end": 30,
            "quote": "text that appears nowhere in this candidate's answer at all",
        }


def _artifact_text_from_prompt(user: str) -> str:
    marker = "offsets from character 0\n"
    if marker not in user:
        return ""
    return user.split(marker, 1)[1].split("\n\n")[0]


def _dimension_keys_from_schema(schema: dict) -> list[str]:
    return list(schema["properties"]["scores"]["items"]["properties"]["dimension_key"]["enum"])


def _artifact_id_from_schema(schema: dict) -> str:
    span = schema["properties"]["scores"]["items"]["properties"]["evidence"]["items"]
    return span["properties"]["artifact_id"]["enum"][0]


@pytest.fixture(autouse=True)
def _service_secret(monkeypatch):
    """A known platform secret, so no test reads or writes the developer's
    machine secret under their home directory (Platform_Core v0.12.0)."""
    monkeypatch.setenv("SERVICE_SECRET", "m13-test-secret")


@pytest.fixture(autouse=True)
def _no_network_llm():
    """No test may reach a real model. Restores whatever was there afterwards."""
    llm_module.set_llm(llm_module.NullLLM())
    yield
    llm_module.set_llm(None)


@pytest.fixture(autouse=True)
def _fresh_rubrics():
    rubrics.reload()
    yield
    rubrics.reload()


@pytest.fixture(name="rubric")
def rubric_fixture():
    return rubrics.get_rubric("dsa_verbal")


@pytest.fixture(name="questions")
def questions_fixture() -> FixtureQuestions:
    return FixtureQuestions()


@pytest.fixture(name="cases")
def cases_fixture():
    return {case.label: case for case in regression_cases()}


@pytest.fixture(name="answer")
def answer_fixture(cases) -> str:
    return cases["hashmap_full_credit"].answer_text


@pytest.fixture(name="artifacts")
def artifacts_fixture(answer: str) -> ArtifactSet:
    artifact = Artifact(artifact_id=uuid.uuid4(), artifact_type="transcript", text=answer)
    frozen = ArtifactSet.freeze([artifact])
    frozen.detect_and_mark_injection()
    return frozen


@pytest.fixture(name="view")
def view_fixture(rubric, questions, answer):
    package = questions.by_label("hashmap_lookup_why")
    return project_for_evaluator(
        question_stem=package.stem,
        reference_answer=package.reference_answer,
        key_points=package.key_points,
        rubric=rubric,
        answer_text=answer,
    )


@pytest.fixture(name="turn")
def turn_fixture(questions, answer) -> TurnInput:
    package = questions.by_label("hashmap_lookup_why")
    return TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=answer,
    )


@pytest.fixture(name="engine")
def engine_fixture():
    """In-memory, per test. No test writes to anyone's dev.db."""
    from backend_M13_Evaluation_Engine import models  # noqa: F401 - registers tables

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Iterator[TestClient]:
    from backend_M13_Evaluation_Engine.app import app

    app.dependency_overrides[get_session] = lambda: session
    # Staff, as in M04's and M15's suites: these tests are about what M13
    # computes, and staff may see any student. Who may ask is tested on its
    # own, with a client that carries no identity (`test_guard.py`).
    with TestClient(app, headers={"X-Role": "admin", "X-Candidate-Id": "test-admin"}) as client:
        yield client
    app.dependency_overrides.clear()

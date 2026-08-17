"""The HTTP surface — §7, and the clone-and-run promise of §6.11."""

from __future__ import annotations

import pytest

from backend_M13_Evaluation_Engine import llm as llm_module

from .conftest import StubLLM


def test_health_reports_the_loaded_rubric_set(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["module"] == "M13"
    assert "dsa_verbal@1.0.0" in body["rubric_set_version"]
    # Nothing is calibrated in this slice, and the endpoint says so rather
    # than implying a gate that has not been passed.
    assert body["calibration_version"] == "none"


def test_status_matches_the_platform_registry(client):
    body = client.get("/status").json()
    assert body["id"] == "M13"


def test_the_registry_knows_this_module_is_built(client):
    """`ai_core.modules_meta` shipped M13 as `implemented: False` for a while.

    The endpoint that exists to tell the platform what is built was reporting
    its own module as unbuilt — which nothing failed on, because nothing
    checked. This is the check.
    """
    assert client.get("/status").json()["implemented"] is True


@pytest.mark.gate
def test_deps_declares_no_required_upstream(client):
    """M13 must not fail because someone else is down.

    Marking a dependency required turns another team's outage into a student
    losing their score, which is the one thing this module cannot do.
    """
    body = client.get("/v1/deps").json()
    assert body["module"] == "M13"
    assert body["dependencies"], "module.json declared no dependencies at all"
    assert not any(d["required"] for d in body["dependencies"])


def test_deps_names_what_breaks_without_each_upstream(client):
    body = client.get("/v1/deps").json()
    for dependency in body["dependencies"]:
        assert dependency["on_missing"].strip(), f"{dependency['module_id']} has no on_missing"
    assert {d["module_id"] for d in body["dependencies"]} == {"M05", "M12", "M04"}


def test_evaluation_is_reported_unavailable_without_a_key(client):
    assert client.get("/v1/deps").json()["evaluation_available"] is False


def test_rubric_listing(client):
    body = client.get("/v1/rubrics").json()
    assert body["rubrics"][0]["round_type"] == "dsa_verbal"
    assert body["rubrics"][0]["concept_bearing"] == "correctness"


def test_rubric_detail_and_404(client):
    assert client.get("/v1/rubrics/dsa_verbal").status_code == 200
    missing = client.get("/v1/rubrics/no_such_round")
    assert missing.status_code == 404
    assert "no rubric" in missing.json()["detail"]


def test_fixtures_endpoint_exposes_the_bank_and_the_suite(client):
    body = client.get("/v1/fixtures").json()
    labels = {q["label"] for q in body["questions"]}
    assert {"hashmap_lookup_why", "two_sum_hashmap"} <= labels
    assert len(body["regression_cases"]) >= 8


def test_evaluate_end_to_end(client, cases):
    llm_module.set_llm(StubLLM("honest"))
    response = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": cases["hashmap_full_credit"].answer_text,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert len(body["aggregated"]) == 3
    assert body["composite"] is None
    for score in body["aggregated"]:
        assert score["evidence"], "a score shipped without evidence"


def test_evaluate_reports_a_missing_question_honestly(client):
    response = client.post(
        "/v1/evaluations", json={"question_label": "nope", "answer_text": "hi"}
    )
    assert response.status_code == 404
    assert "question" in response.json()["detail"].lower()


def test_hint_level_shows_up_in_the_credited_score(client, cases):
    llm_module.set_llm(StubLLM("honest", score=4))
    response = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": cases["hashmap_full_credit"].answer_text,
            "hint_level_used": 2,
        },
    )
    body = response.json()
    for score in body["aggregated"]:
        assert score["raw_score"] == 4
        assert score["credited_score"] == pytest.approx(3.4)


def test_model_confidence_is_not_the_badge(client, cases):
    """§8.1 — `model_confidence` feeds ECE and is never rendered.

    It is present in the stored record on purpose; what matters is that
    `agreement` is a separate field, so a UI cannot accidentally show the
    model's opinion of itself as though it were ensemble evidence.
    """
    llm_module.set_llm(StubLLM("honest"))
    body = client.post(
        "/v1/evaluations",
        json={
            "question_label": "hashmap_lookup_why",
            "answer_text": cases["hashmap_full_credit"].answer_text,
        },
    ).json()
    assert "agreement" in body
    assert set(body["agreement"].values()) == {"medium"}
    assert all("model_confidence" in s for s in body["aggregated"])

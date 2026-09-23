"""What M13 sends other modules — the shapes a merge depends on.

These are the tests worth having before M02, M04's next milestone, M12, M16,
M17 and M19 are built against them. Every one asserts a property another
module's code will rely on, so if someone changes a field name here the break
shows up in this repo rather than in theirs.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from backend_M13_Evaluation_Engine import emit
from backend_M13_Evaluation_Engine.adapters import ItemParams
from backend_M13_Evaluation_Engine.contracts import N_CATEGORIES
from backend_M13_Evaluation_Engine.service import TurnInput, evaluate_turn, outbound

from .conftest import StubLLM

CONSENT = uuid.uuid4()


#: M04's communication domain, as `GET /v1/concepts` answers it. In
#: production these come from M04 (`adapters.ConceptDomains`) rather than
#: from a list — see `test_communication_concepts_are_m04s_to_name`.
COMMS = frozenset({"concept:thinking_aloud", "concept:summarising_concisely"})


def also_naming(package, *concept_ids):
    """The same package, plus these concepts. A COPY: the question fixtures
    are shared, and a test that mutates one changes the next one's bank."""
    return replace(package, concepts={**package.concepts, **{c: 1.0 for c in concept_ids}})


@pytest.fixture(name="scored")
def scored_fixture(questions, cases, rubric):
    """A complete evaluation with consent, plus its rubric and package."""
    package = questions.by_label("hashmap_lookup_why")
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=cases["hashmap_full_credit"].answer_text,
        consent_id=CONSENT,
    )
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"), question=package)
    return evaluation, rubric, package


# ── M04: the mastery write path ──────────────────────────────────────────


@pytest.mark.gate
def test_the_namespace_matches_m04s_published_value():
    """M04 derives the same id and inserts on conflict-do-nothing.

    Derive it differently and a replay stops being a no-op and starts being a
    second answer about the same turn — silently, inside theta.
    """
    assert emit.OBS_NAMESPACE == uuid.UUID("6f1c1d3e-0000-4000-8000-000000000004")


def test_observation_id_is_stable_and_keyed_as_m04_keys_it():
    turn_id, session_id = uuid.uuid4(), uuid.uuid4()
    args = dict(
        turn_id=turn_id,
        session_id=session_id,
        concept_id="concept:hash_maps",
        kind="answer_scored",
        rubric_version="1.0.0",
    )
    assert emit.observation_id(**args) == emit.observation_id(**args)
    # The rubric version is part of the key: a re-score under a new rubric is
    # genuinely a different observation and must not collide with the old one.
    assert emit.observation_id(**{**args, "rubric_version": "2.0.0"}) != emit.observation_id(**args)


@pytest.mark.gate
def test_only_the_concept_bearing_dimension_reaches_technical_concepts(scored):
    """AC-13.18 — the rule that stops communication becoming DSA mastery."""
    evaluation, rubric, package = scored
    package = also_naming(package, *COMMS)
    observations = emit.observations_for(evaluation, rubric, package, communication_concepts=COMMS)
    assert observations
    # Both sides of the rule are exercised, or the gate proves nothing.
    assert {o.concept_id for o in observations} & COMMS

    for obs in observations:
        if obs.concept_id in COMMS:
            dimension = rubric.dimension(obs.source_dimension_key)
            assert dimension.concept_domain == "communication"
        else:
            assert obs.source_dimension_key == rubric.concept_bearing_key


@pytest.mark.gate
def test_a_communication_score_with_no_concept_writes_nothing(scored):
    """Run live, this wrote `concept:communication` — an id in no ontology.

    M04 rejected the whole batch as "unknown concept", which took the turn's
    TECHNICAL observation down with it, so a fully scored interview moved
    nothing at all. A score with nowhere true to go is not a belief.
    """
    evaluation, rubric, package = scored
    assert not set(package.concepts) & COMMS  # the bank item names none

    observations = emit.observations_for(evaluation, rubric, package, communication_concepts=COMMS)
    assert observations, "the technical observation still goes"
    assert all(o.source_dimension_key == rubric.concept_bearing_key for o in observations)
    assert not any("communication" in o.concept_id for o in observations)


def test_without_m04_no_communication_observation_is_invented(scored):
    """Rule 2: a missing upstream narrows what is claimed.

    With no ontology to ask, the communication DIMENSION writes nothing — no
    minted id, no guess. The score itself is still on the evaluation a student
    reads; it just does not become a belief about a concept.
    """
    evaluation, rubric, package = scored
    package = also_naming(package, *COMMS)
    observations = emit.observations_for(
        evaluation, rubric, package, communication_concepts=frozenset()
    )
    assert observations
    written_by = {o.source_dimension_key for o in observations}
    assert written_by == {rubric.concept_bearing_key}
    assert not any(
        rubric.dimension(key).concept_domain == "communication" for key in written_by
    )
    assert any(s.dimension_key == "communication" for s in evaluation.aggregated)


def test_depth_produces_no_observation_at_all(scored):
    """`depth` is a score a student reads, not a belief about a concept."""
    evaluation, rubric, package = scored
    keys = {o.source_dimension_key for o in emit.observations_for(evaluation, rubric, package)}
    assert "depth" not in keys


def test_observation_carries_the_ordinal_not_just_a_float(scored):
    """M04 §6.3: `outcome` is display/BKT only and is NOT the likelihood input.

    GRM needs the un-normalised category, so `raw_category` and `n_categories`
    are what make the observation fittable at all.
    """
    evaluation, rubric, package = scored
    obs = emit.observations_for(evaluation, rubric, package)[0]
    assert obs.raw_category in range(N_CATEGORIES)
    assert obs.n_categories == N_CATEGORIES
    assert 0.0 <= obs.outcome <= 1.0


def test_without_an_item_the_observation_is_not_theta_eligible(scored):
    """M5 absent → no calibrated item → M04 must not move theta (M04 §6.3)."""
    evaluation, rubric, package = scored
    assert package.item is None
    obs = emit.observations_for(evaluation, rubric, package)[0]
    assert obs.response_model == "none"
    assert obs.item is None


def test_with_an_item_it_is_grm(scored):
    evaluation, rubric, package = scored
    package.item = ItemParams(question_id=package.question_id, a=1.2, b=0.3)
    obs = emit.observations_for(evaluation, rubric, package)[0]
    assert obs.response_model == "grm"
    assert obs.item["a"] == 1.2


@pytest.mark.gate
def test_no_consent_means_no_observation(scored):
    """M04 requires consent_id with no default; so do we, at build time."""
    evaluation, rubric, package = scored
    evaluation.consent_id = None
    with pytest.raises(emit.NoConsent):
        emit.observations_for(evaluation, rubric, package)


def test_evidence_travels_with_every_observation(scored):
    """M04 refuses an observation whose evidence does not resolve (FR-4.5)."""
    evaluation, rubric, package = scored
    for obs in emit.observations_for(evaluation, rubric, package):
        assert obs.evidence
        for ref in obs.evidence:
            assert ref["checksum"]
            assert ref["span"]["quote"]


def test_hint_assisted_answers_are_weighted_once(scored):
    """M04 §6.3: `weight × 0.7`, applied HERE, and M04 does not re-apply it."""
    evaluation, rubric, package = scored
    for score in evaluation.aggregated:
        score.hint_level_used = 2
    obs = emit.observations_for(evaluation, rubric, package)[0]
    assert obs.weight == pytest.approx(0.7)


def test_the_m04_url_is_the_one_m04_actually_serves():
    """Checked against its router, not against the plan — the plan was wrong."""
    candidate = uuid.uuid4()
    assert emit.observations_url(candidate).endswith(f"/v1/candidates/{candidate}/observations")
    assert "/v1/observations" not in emit.observations_url(candidate)


# ── M19: the evidence ledger ─────────────────────────────────────────────


def test_ledger_entry_matches_m19s_claim_shape(scored):
    evaluation, _, _ = scored
    entries = emit.ledger_entries(evaluation)
    assert entries
    for entry in entries:
        assert entry["claim_kind"] == "dimension_score"
        assert set(entry) >= {
            "candidate_id",
            "session_id",
            "turn_id",
            "claim_kind",
            "claim_key",
            "value",
            "evidence",
            "versions",
            "computed_at",
        }
        assert entry["versions"]["code_sha"]


# ── M02: the coverage ledger ─────────────────────────────────────────────


def test_coverage_update_moves_the_row_to_scored(scored):
    """M02 §6 — the transition that makes coverage a guarantee."""
    evaluation, rubric, _ = scored
    update = emit.coverage_update(evaluation, rubric)
    assert update["state"] == "scored"
    assert update["score"] is not None
    assert update["rubric_version"] == "1.0.0"


def test_coverage_takes_the_concept_bearing_score(scored):
    """A requirement is covered by whether they could do it, not how they said it."""
    evaluation, rubric, _ = scored
    bearing = next(
        s for s in evaluation.aggregated if s.dimension_key == rubric.concept_bearing_key
    )
    update = emit.coverage_update(evaluation, rubric)
    assert update["raw_category"] == bearing.raw_score
    # On 0..1, because M02 keeps one ledger across rubrics of different scales.
    assert update["score"] == pytest.approx(bearing.raw_score / (update["n_categories"] - 1))
    assert 0.0 <= update["score"] <= 1.0


# ── the bundle ───────────────────────────────────────────────────────────


def test_outbound_bundles_all_three_so_none_is_forgotten(scored):
    evaluation, rubric, package = scored
    payload = outbound(evaluation, rubric, package)
    assert payload["observations"]
    assert payload["ledger"]
    assert payload["coverage"]
    assert payload["observations_skipped"] is None


def test_outbound_degrades_loudly_without_consent(scored):
    evaluation, rubric, package = scored
    evaluation.consent_id = None
    payload = outbound(evaluation, rubric, package)
    assert payload["observations"] == []
    assert "consent" in str(payload["observations_skipped"]).lower()
    # The ledger and coverage rows still go: they are not personal-data writes
    # into a durable belief, and losing them would lose the report too.
    assert payload["ledger"] and payload["coverage"]

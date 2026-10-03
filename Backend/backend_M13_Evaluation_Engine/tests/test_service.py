"""Orchestration — §6.4's composition rules and §6.1's hint credit."""

from __future__ import annotations

import pytest

from backend_M13_Evaluation_Engine.contracts import (
    Agreement,
    DimensionScore,
    EvaluationStatus,
)
from backend_M13_Evaluation_Engine.ensemble import N1_PRACTICE, agreement_for
from backend_M13_Evaluation_Engine.service import (
    apply_hint_credit,
    compose,
    evaluate_turn,
    freeze_artifacts,
)

from .conftest import StubLLM

# ── §6.4 step 0 ──────────────────────────────────────────────────────────


def test_freeze_records_a_checksum_per_artifact(turn):
    frozen = freeze_artifacts(turn)
    assert len(frozen.checksums) == 1
    assert all(len(c) == 64 for c in frozen.checksums.values())


def test_freeze_detects_injection_without_mutating(questions, cases):
    import uuid

    from backend_M13_Evaluation_Engine.service import TurnInput

    text = cases["injection_mid_answer"].answer_text
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=questions.by_label("hashmap_lookup_why").question_id,
        answer_text=text,
    )
    frozen = freeze_artifacts(turn)
    assert frozen.neutralised
    assert frozen.artifacts[turn.turn_id].text == text


# ── §6.1 hint credit ─────────────────────────────────────────────────────


@pytest.mark.gate
def test_hint_credit_leaves_raw_score_untouched(rubric):
    """The corpus has to stay comparable across hinted and unhinted answers."""
    scores = [DimensionScore(dimension_key="correctness", raw_score=4)]
    apply_hint_credit(scores, rubric, hint_level=2)

    assert scores[0].raw_score == 4, "raw must survive so calibration stays comparable"
    assert scores[0].credited_score == pytest.approx(4 * 0.85)
    assert scores[0].hint_level_used == 2


def test_no_hint_credits_fully(rubric):
    scores = [DimensionScore(dimension_key="correctness", raw_score=3)]
    apply_hint_credit(scores, rubric, hint_level=0)
    assert scores[0].credited_score == 3.0


def test_hint_penalty_is_applied_once_not_compounded(rubric):
    """M04 §6.3: applied once, HERE, and M04 does not re-apply it."""
    scores = [DimensionScore(dimension_key="correctness", raw_score=4)]
    apply_hint_credit(scores, rubric, hint_level=3)
    first = scores[0].credited_score
    apply_hint_credit(scores, rubric, hint_level=3)
    assert scores[0].credited_score == first


# ── §6.4 step 7 composition ──────────────────────────────────────────────


@pytest.mark.gate
def test_composite_is_none_while_the_display_gate_is_closed(rubric):
    scores = [DimensionScore(dimension_key=d.key, raw_score=3) for d in rubric.dimensions]
    assert compose(scores, rubric) is None


def test_composite_is_none_if_any_dimension_is_uncalibrated(rubric):
    """A composite over whichever subset happens to be calibrated is a
    different measurement each week."""
    scores = [DimensionScore(dimension_key=d.key, raw_score=3) for d in rubric.dimensions]
    for score in scores:
        score.calibrated_score = 3.0
    scores[1].calibrated_score = None
    assert compose(scores, rubric) is None


def test_composite_is_weighted_when_everything_is_calibrated(rubric):
    scores = []
    for dimension in rubric.dimensions:
        score = DimensionScore(dimension_key=dimension.key, raw_score=3)
        score.calibrated_score = 4.0 if dimension.key == "correctness" else 2.0
        scores.append(score)

    result = compose(scores, rubric)
    expected = (4.0 * 0.40 + 2.0 * 0.35 + 2.0 * 0.25) / (0.40 + 0.35 + 0.25)
    assert result == pytest.approx(expected, abs=1e-3)


# ── agreement (§8.1) ─────────────────────────────────────────────────────


@pytest.mark.gate
def test_a_single_evaluator_is_never_high_agreement():
    """"1 of 1 agreed" is not evidence, and §8.1 forbids rendering it as such."""
    assert agreement_for(0, members=1) is Agreement.medium


def test_ensemble_agreement_tracks_spread():
    assert agreement_for(0, members=3) is Agreement.high
    assert agreement_for(1, members=3) is Agreement.medium
    assert agreement_for(2, members=3) is Agreement.low


# ── end to end ───────────────────────────────────────────────────────────


def test_evaluate_turn_produces_a_complete_evaluation(turn):
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"))

    assert evaluation.status is EvaluationStatus.complete
    assert evaluation.ensemble_config == N1_PRACTICE.name
    assert len(evaluation.aggregated) == 3
    assert evaluation.composite is None, "nothing is calibrated yet, so no number"
    assert evaluation.artifact_checksums
    assert evaluation.versions.rubric_version == "1.0.0"
    assert evaluation.versions.model_id == N1_PRACTICE.name


@pytest.mark.gate
def test_every_displayed_score_carries_verified_evidence(turn):
    """AC-13.1, on the pipeline's own output."""
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"))
    for score in evaluation.aggregated:
        assert score.evidence, f"{score.dimension_key} has a score and no evidence"
        for ref in score.evidence:
            assert ref.span is not None and ref.span.verified


def test_unverifiable_evidence_routes_to_human_review(turn):
    evaluation = evaluate_turn(turn, llm=StubLLM("fabricated"))
    assert evaluation.status is EvaluationStatus.needs_human_review
    assert evaluation.aggregated == []


def test_no_api_key_does_not_crash_the_turn(turn):
    from backend_M13_Evaluation_Engine.llm import NullLLM

    evaluation = evaluate_turn(turn, llm=NullLLM())
    assert evaluation.status is EvaluationStatus.needs_human_review
    assert evaluation.evaluators[0].dropped_reason == "no_api_key"


def test_delivery_is_absent_not_zero(turn):
    """EC-13.14 / Rule 2 — M12 is Phase 3 and its absence omits a section."""
    evaluation = evaluate_turn(turn, llm=StubLLM("honest"))
    assert evaluation.delivery is None


@pytest.mark.gate
def test_only_scored_delivery_signals_can_reach_a_numeric():
    """AC-13.17 — M12's validity gate has to survive the module boundary.

    M12 FR-12.10 is P0: no signal reaches `scored` without a completed validity
    record. Flattening delivery to `dict[str, float]` here would erase
    `disposition`, and the gate that makes the facial-analysis work defensible
    rather than a liability would stop being enforceable one module downstream.
    Carrying the type is what keeps it checkable — this is that check.
    """
    from backend_M13_Evaluation_Engine.contracts import (
        DeliveryAssessment,
        DeliveryDisposition,
    )

    delivery = DeliveryAssessment(
        subscores={"fluency": 3.0, "presence": 2.0, "clarity": 4.0, "structure": 1.0},
        dispositions={
            "fluency": DeliveryDisposition.scored,
            "presence": DeliveryDisposition.coaching,
            "clarity": DeliveryDisposition.diagnostic,
            "structure": DeliveryDisposition.suppressed,
        },
    )

    assert delivery.scored_subscores() == {"fluency": 3.0}

    # A signal with no recorded disposition is NOT scored. Defaulting the other
    # way would make an un-validated signal count, which is the exact failure
    # M12's protocol exists to prevent.
    unknown = DeliveryAssessment(subscores={"mystery": 4.0}, dispositions={})
    assert unknown.scored_subscores() == {}


def test_the_lexical_fallback_only_calls_a_point_missing_when_its_words_are_absent():
    """2026-10-04, found live: a complete answer paraphrased all three key
    points (0.43, 0.43, 0.25 shared words), the evaluator said nothing was
    missing, and the lexical fallback — held to the entailment bar — told the
    student they had covered none of them."""
    from backend_M13_Evaluation_Engine.coverage import Coverage

    paraphrased = Coverage(scores={"kp_1": 0.43, "kp_2": 0.43, "kp_3": 0.25}, method="lexical")
    assert paraphrased.missing() == []
    absent = Coverage(scores={"kp_1": 0.43, "kp_2": 0.1}, method="lexical")
    assert absent.missing() == ["kp_2"]
    # The entailment model keeps its own bar.
    assert Coverage(scores={"kp_1": 0.43}, method="nli").missing() == ["kp_1"]

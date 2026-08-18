"""The ensemble, calibration and the outbox — milestones M4, M5 and M9."""

from __future__ import annotations

import uuid

import pytest

from backend_M13_Evaluation_Engine import calibration as calib
from backend_M13_Evaluation_Engine import store
from backend_M13_Evaluation_Engine.contracts import Agreement, EvaluatorOutput
from backend_M13_Evaluation_Engine.ensemble import (
    N1_PRACTICE,
    N3_HETEROGENEOUS,
    EnsembleConfig,
    InvalidEnsemble,
    Member,
    aggregate,
    agreement_for,
    needs_adjudication,
)
from backend_M13_Evaluation_Engine.ensemble import run as run_ensemble
from backend_M13_Evaluation_Engine.evaluator import EvaluationRequest
from backend_M13_Evaluation_Engine.service import TurnInput, evaluate_turn, outbound

from .conftest import StubLLM


def _request(view, artifacts) -> EvaluationRequest:
    return EvaluationRequest(
        view=view,
        artifacts=artifacts,
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        context={"round_type": view.rubric.round_type},
    )


# ── FR-13.26: an ensemble that would lie about its own confidence ────────


@pytest.mark.gate
def test_a_homogeneous_ensemble_is_rejected(view, artifacts):
    """Two members, same model, same seed = one sample twice.

    These models take no sampling parameter, so `spread` would collapse to 0
    and the badge would report determinism as agreement. Rejected rather than
    discouraged.
    """
    bad = EnsembleConfig(name="bad", members=(Member(seed=0), Member(seed=0)))
    assert bad.homogeneous_without_decorrelation()
    with pytest.raises(InvalidEnsemble, match="one sample twice"):
        run_ensemble(_request(view, artifacts), bad, llm=StubLLM("honest"))


def test_the_shipped_default_is_decorrelated():
    assert not N3_HETEROGENEOUS.homogeneous_without_decorrelation()
    assert len({m.seed for m in N3_HETEROGENEOUS.members}) == N3_HETEROGENEOUS.size


def test_a_single_member_is_trivially_valid():
    assert not N1_PRACTICE.homogeneous_without_decorrelation()


# ── aggregation ──────────────────────────────────────────────────────────


def _output(index: int, scores: dict[str, int]) -> EvaluatorOutput:
    from backend_M13_Evaluation_Engine.contracts import DimensionScore

    return EvaluatorOutput(
        evaluator_index=index,
        model_id="stub",
        prompt_version="v",
        scores=[
            DimensionScore(dimension_key=k, raw_score=v, reasoning=f"e{index} on {k}")
            for k, v in scores.items()
        ],
    )


def test_median_not_mean():
    """A mean invents a 2.67 that no anchor describes and no rater could give."""
    result = aggregate(
        [
            _output(0, {"correctness": 2}),
            _output(1, {"correctness": 3}),
            _output(2, {"correctness": 4}),
        ]
    )
    assert result.aggregated[0].raw_score == 3


def test_spread_is_max_minus_min():
    result = aggregate([_output(0, {"depth": 1}), _output(1, {"depth": 4})])
    assert result.spread_levels["depth"] == 3


def test_the_reasoning_shown_is_from_the_member_who_gave_the_median():
    """A merged paragraph would be a sentence nobody wrote about a score
    nobody gave."""
    result = aggregate(
        [_output(0, {"depth": 1}), _output(1, {"depth": 3}), _output(2, {"depth": 4})]
    )
    assert result.aggregated[0].reasoning == "e1 on depth"


def test_a_dropped_evaluator_does_not_vote():
    dropped = _output(2, {"depth": 0})
    dropped.dropped_reason = "evidence_unverifiable"
    result = aggregate([_output(0, {"depth": 3}), _output(1, {"depth": 3}), dropped])
    assert result.aggregated[0].raw_score == 3
    assert result.spread_levels["depth"] == 0


def test_agreement_needs_more_than_one_voice():
    assert agreement_for(0, members=1) is Agreement.medium
    assert agreement_for(0, members=3) is Agreement.high
    assert agreement_for(2, members=3) is Agreement.low


def test_adjudication_fires_at_two_levels():
    assert needs_adjudication(aggregate([_output(0, {"d": 1}), _output(1, {"d": 3})]))
    assert not needs_adjudication(aggregate([_output(0, {"d": 2}), _output(1, {"d": 3})]))


def test_three_members_produce_three_evaluator_records(view, artifacts):
    result = run_ensemble(_request(view, artifacts), N3_HETEROGENEOUS, llm=StubLLM("honest"))
    assert len(result.outputs) == 3
    assert {o.dimension_order_seed for o in result.outputs} == {0, 17, 41}


# ── calibration and the display gate (§6.7) ──────────────────────────────


def _pairs(n: int, *, offset: float = 0.0, length: int = 100) -> list[calib.Pair]:
    out = []
    for i in range(n):
        raw = i % 5
        out.append(
            calib.Pair(
                raw=raw,
                human=max(0.0, min(4.0, raw + offset)),
                length_tokens=length,
                model_confidence=0.9,
                correct=(i % 10) != 0,  # ~90% correct, matching the stated confidence
            )
        )
    return out


def test_qwk_of_perfect_agreement_is_one():
    values = [0, 1, 2, 3, 4] * 6
    assert calib.quadratic_weighted_kappa(values, values) == pytest.approx(1.0)


def test_qwk_punishes_a_two_level_miss_more_than_two_one_level_misses():
    """Quadratic weights, which is the whole reason QWK and not linear kappa.

    The reference has to VARY: against a constant rater kappa is degenerate
    and every prediction scores 0, which is a property of the statistic rather
    than of the predictions.
    """
    truth = [0, 1, 2, 3, 4] * 8
    near = [min(4, t + 1) for t in truth]
    far = [min(4, t + 2) for t in truth]
    assert calib.quadratic_weighted_kappa(near, truth) > calib.quadratic_weighted_kappa(far, truth)


def test_isotonic_mapping_never_decreases():
    """A higher raw score mapping to a lower human one is a bug that would
    tell a student their better answer scored worse."""
    table = calib.fit_isotonic(
        [calib.Pair(raw=0, human=1.0), calib.Pair(raw=1, human=0.2), calib.Pair(raw=2, human=3.0)]
    )
    values = [table[k] for k in sorted(table)]
    assert values == sorted(values)


@pytest.mark.gate
def test_the_gate_is_closed_below_the_minimum_sample():
    fit = calib.fit(
        dimension_key="depth", round_type="dsa_verbal", ensemble_config="n3_het_v1",
        pairs=_pairs(5),
    )
    assert not fit.gate.display_numeric
    assert "sample" in fit.gate.reasons
    assert fit.method == "identity"


@pytest.mark.gate
def test_the_gate_says_why_in_words_a_human_can_read():
    fit = calib.fit(
        dimension_key="depth", round_type="dsa_verbal", ensemble_config="n3_het_v1",
        pairs=_pairs(40), qwk_overall=0.2,
    )
    assert not fit.gate.display_numeric
    assert "qwk_overall" in fit.gate.reasons
    assert "0.20" in fit.gate.reasons["qwk_overall"]
    assert fit.gate.student_note and "isn't accurate enough" in fit.gate.student_note


def test_a_passing_fit_opens_the_gate():
    fit = calib.fit(
        dimension_key="correctness", round_type="dsa_verbal", ensemble_config="n3_het_v1",
        pairs=_pairs(60), qwk_overall=0.9,
    )
    assert fit.gate.display_numeric, fit.gate.reasons
    assert fit.gate.student_note is None


def test_length_bias_is_measured_in_score_levels_per_log_token():
    """A model that scores long answers higher than the humans did."""
    pairs = [
        calib.Pair(raw=4, human=2.0, length_tokens=1000),
        calib.Pair(raw=4, human=2.0, length_tokens=900),
        calib.Pair(raw=2, human=2.0, length_tokens=50),
        calib.Pair(raw=2, human=2.0, length_tokens=40),
    ]
    assert calib.length_bias_beta(pairs) > 0.15


def test_no_length_bias_when_the_residual_is_flat():
    assert calib.length_bias_beta(_pairs(40)) == pytest.approx(0.0, abs=0.01)


# ── the outbox (§6.11) ───────────────────────────────────────────────────


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


def test_observations_queue_rather_than_being_sent_inline(session, saved):
    pending = store.pending_observations(session)
    assert pending
    assert all(p.state == "pending" for p in pending)


@pytest.mark.gate
def test_m04_being_down_does_not_fail_the_evaluation(session, saved):
    """The rule this module cannot break: a student's score never depends on
    whether somebody else's service was up."""
    def dead(candidate_id, observations):
        return False, "URLError: connection refused"

    result = store.drain(session, sender=dead)
    assert result["failed"] and result["sent"] == 0
    # ...and the evaluation is untouched and still readable.
    assert store.latest_for_turn(session, saved.turn_id) is not None
    # Still pending, so it will go when M04 comes back.
    assert store.pending_observations(session)


def test_a_successful_drain_marks_them_sent(session, saved):
    sent_batches = []

    def ok(candidate_id, observations):
        sent_batches.append((candidate_id, observations))
        return True, "http_200"

    result = store.drain(session, sender=ok)
    assert result["sent"] and result["pending"] == 0
    assert len(sent_batches) == 1, "one batched call per candidate, not one per observation"


def test_a_4xx_is_not_retried_forever(session, saved):
    def rejected(candidate_id, observations):
        return False, "http_422: evidence does not resolve"

    store.drain(session, sender=rejected)
    assert not store.pending_observations(session)


def test_a_rescore_retracts_rather_than_compensating(session, saved, questions, cases, rubric):
    """M04 recomputes from surviving observations (M04 §6.2, FR-13.29)."""
    package = questions.by_label("hashmap_lookup_why")
    store.drain(session, sender=lambda c, o: (True, "http_200"))

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

    retractions = [p for p in store.pending_observations(session) if p.payload.get("retracted")]
    assert retractions, "a sent observation must be retracted, not left standing"
    assert all(r.payload["retraction_reason"] == "rescore" for r in retractions)

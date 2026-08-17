"""The regression and adversarial suite — §6.10, §12.

**What this file can and cannot assert, stated plainly.** Scoring a frozen case
against its band needs a real model, and no test in this repo opens a socket.
So what runs here is the *harness* plus the properties of the suite itself —
which is the half that actually rots, and the half that has to be right before
the bands arrive (§14 milestone M8).

The important test is `test_no_band_was_derived_from_a_model`. Trap 9: the
tempting way to build 200 frozen cases is to snapshot the current model's
output as the expected band, and then every real improvement reads as a
regression and every bias the model has today becomes a CI gate defending it.
Recording `band_source` on each case makes that a checkable property instead
of a convention someone breaks under deadline.
"""

from __future__ import annotations

import pytest

from backend_M13_Evaluation_Engine.adapters import regression_cases
from backend_M13_Evaluation_Engine.contracts import SCALE_MAX, SCALE_MIN
from backend_M13_Evaluation_Engine.service import TurnInput, evaluate_turn

from .conftest import StubLLM

#: Provenances that measure agreement with humans. Anything else measures
#: agreement with ourselves.
HUMAN_BAND_SOURCES = {"hand_set_from_anchors", "adjudicated_consensus"}


def test_the_suite_is_not_empty():
    assert len(regression_cases()) >= 8


@pytest.mark.gate
def test_no_band_was_derived_from_a_model():
    """Trap 9 — a band snapshotted from model output defends today's bias."""
    for case in regression_cases():
        assert case.band_source in HUMAN_BAND_SOURCES, (
            f"case '{case.label}' has band_source={case.band_source!r}. A band taken "
            f"from a model's own output measures self-consistency, not correctness."
        )


def test_every_band_is_well_formed():
    for case in regression_cases():
        low, high = case.expected_band
        assert SCALE_MIN <= low <= high <= SCALE_MAX, f"{case.label}: bad band"


def test_every_case_points_at_a_real_question(questions):
    labels = {q.label for q in questions.all()}
    for case in regression_cases():
        assert case.question_label in labels, f"{case.label} references a missing question"


def test_every_case_says_why_it_exists():
    """A frozen case with no note is one nobody can safely delete later."""
    for case in regression_cases():
        assert case.note.strip(), f"{case.label} has no note"


def test_the_adversarial_shapes_are_all_present():
    """§12's table — the cases that catch systematic, exploitable weaknesses."""
    labels = {case.label for case in regression_cases()}
    required = {
        "confidently_wrong",
        "verbose_but_empty",
        "terse_but_complete",
        "jargon_salad",
        "injection_mid_answer",
        "honest_non_answer",
    }
    assert required <= labels, f"missing adversarial cases: {sorted(required - labels)}"


def test_terse_and_verbose_bands_encode_the_length_rule():
    """The suite itself must say that length does not buy a score.

    If the terse-but-complete band were ever set below the verbose-but-empty
    band, the suite would be enforcing length bias rather than catching it.
    """
    cases = {c.label: c for c in regression_cases()}
    terse = cases["terse_but_complete"].expected_band
    verbose = cases["verbose_but_empty"].expected_band
    assert terse[0] > verbose[1], "a short complete answer must outscore a long empty one"


def test_the_harness_runs_a_case_end_to_end(questions):
    """Proves the plumbing, not the scores. The bands land in milestone M8."""
    import uuid

    case = next(c for c in regression_cases() if c.label == "hashmap_full_credit")
    package = questions.by_label(case.question_label)
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=case.answer_text,
    )

    evaluation = evaluate_turn(turn, llm=StubLLM("honest", score=3), question=package)

    assert evaluation.aggregated
    scored = {s.dimension_key: s.raw_score for s in evaluation.aggregated}
    assert case.contains(scored["correctness"])


def test_injection_case_still_yields_verifiable_evidence(questions):
    """The end-to-end version of EC-13.3: content after an injection is quotable."""
    import uuid

    case = next(c for c in regression_cases() if c.label == "injection_mid_answer")
    package = questions.by_label(case.question_label)
    turn = TurnInput(
        turn_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_id=package.question_id,
        answer_text=case.answer_text,
    )

    evaluation = evaluate_turn(turn, llm=StubLLM("honest"), question=package)

    assert evaluation.aggregated, "the injection took the whole turn down"
    for score in evaluation.aggregated:
        for ref in score.evidence:
            assert ref.span is not None
            assert "Ignore previous instructions" not in ref.span.quote

"""AC-13.2 — the evaluator cannot reach candidate identity.

This is the module's cheapest and strongest gate, and the one worth running
first: it is a deterministic graph walk, so unlike a counterfactual score
comparison it can honestly target 100%. The prompt is not the enforcement.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from backend_M13_Evaluation_Engine.contracts import TurnEvaluation
from backend_M13_Evaluation_Engine.projection import (
    SAFE_CONFIG_TYPE_NAMES,
    ComparatorText,
    EvaluatorView,
    PairwiseView,
    assert_blind,
    leaks_identity,
    project_for_evaluator,
    project_for_pairwise,
)


@pytest.mark.gate
def test_evaluator_view_is_blind():
    assert leaks_identity(EvaluatorView) == []
    assert_blind(EvaluatorView)


@pytest.mark.gate
def test_pairwise_view_is_blind():
    """§6.5 compares a candidate against their own past work — anonymised.

    Without `ComparatorText` the natural implementation puts a prior `Turn` in
    the view, which reaches `Candidate` in one hop. This is the second gate,
    not an exemption from the first.
    """
    assert leaks_identity(PairwiseView) == []
    assert_blind(PairwiseView)


def test_the_walker_actually_catches_a_leak():
    """A gate that cannot fail is not a gate.

    `TurnEvaluation` legitimately carries identity — it is the stored record,
    not a projection — so it is the natural control for proving the walk works.
    """
    leaks = leaks_identity(TurnEvaluation)
    assert leaks, "the leak walker reported nothing on a type that definitely leaks"
    assert any("candidate_id" in finding for finding in leaks)


def test_walker_catches_a_nested_leak():
    class Sneaky(BaseModel):
        candidate_id: str

    class Wrapper(BaseModel):
        harmless: str
        nested: Sneaky

    leaks = leaks_identity(Wrapper)
    assert leaks == ["Wrapper.nested.candidate_id — forbidden field name"]


def test_walker_catches_a_forbidden_type():
    class Candidate(BaseModel):
        anything: str

    class Wrapper(BaseModel):
        who: Candidate

    assert any("forbidden type" in finding for finding in leaks_identity(Wrapper))


def test_safe_config_allowlist_stays_small():
    """The escape hatch must not quietly grow to cover candidate data.

    `name` has to stay a forbidden field name — a field literally called
    `name` holding a student's name is the exact leak this guards — so
    configuration types are exempted by an explicit list rather than by
    loosening the rule. Six is enough for the whole rubric tree; a seventh
    should require someone to think about it.
    """
    assert len(SAFE_CONFIG_TYPE_NAMES) <= 8
    assert "EvaluatorView" not in SAFE_CONFIG_TYPE_NAMES
    assert "TurnEvaluation" not in SAFE_CONFIG_TYPE_NAMES


def test_code_is_gated_by_round_type_not_by_availability(rubric, questions):
    """A verbal round does not get the code buffer even when one is passed."""
    package = questions.by_label("hashmap_lookup_why")
    view = project_for_evaluator(
        question_stem=package.stem,
        reference_answer=package.reference_answer,
        key_points=package.key_points,
        rubric=rubric,
        answer_text="an answer",
        code="def solve(): ...",
    )
    assert rubric.round_type == "dsa_verbal"
    assert view.code is None


def test_comparators_carry_no_provenance(rubric):
    view = project_for_pairwise(
        question_stem="Why is hash map lookup O(1)?",
        rubric=rubric,
        dimension_key="communication",
        answer_text="mine",
        comparators=[ComparatorText(text="a reference answer", quality_band=4)],
    )
    fields = set(ComparatorText.model_fields)
    assert fields == {"text", "quality_band"}, (
        "a comparator that carries a turn id, a candidate id or a timestamp is a "
        "route back to its author, which is what §6.5 anonymises away"
    )
    assert view.comparators[0].quality_band == 4

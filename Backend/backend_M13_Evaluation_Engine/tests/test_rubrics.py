"""Rubric loading — §6.1's rules, enforced at load rather than at scoring time."""

from __future__ import annotations

import pytest

from backend_M13_Evaluation_Engine.contracts import AppliesWhen, RubricDimension
from backend_M13_Evaluation_Engine.rubrics import RubricError, parse_rubric

BASE = {
    "round_type": "test_round",
    "version": "1.0.0",
    "hint_penalty": {0: 1.0, 1: 0.9},
    "dimensions": [
        {
            "key": "correctness",
            "name": "Correctness",
            "description": "d",
            "concept_bearing": True,
            "anchors": {0: "a", 1: "b", 2: "c", 3: "d", 4: "e"},
        }
    ],
}


def _rubric(**overrides):
    raw = {**BASE, **overrides}
    return parse_rubric(raw, source="test")


def test_the_shipped_rubric_loads(rubric):
    assert rubric.round_type == "dsa_verbal"
    assert rubric.concept_bearing_key == "correctness"
    assert len(rubric.dimensions) == 3


def test_shipped_rubric_routes_communication_away_from_technical(rubric):
    """The rule that stops communication quality becoming DSA mastery."""
    comms = rubric.dimension("communication")
    assert comms.concept_domain == "communication"
    assert not comms.concept_bearing
    assert rubric.dimension(rubric.concept_bearing_key).concept_domain == "technical"


# ── anchors ──────────────────────────────────────────────────────────────


def test_missing_anchor_level_fails_to_load():
    with pytest.raises(RubricError, match="missing anchors"):
        _rubric(
            dimensions=[
                {
                    "key": "k",
                    "name": "n",
                    "description": "d",
                    "concept_bearing": True,
                    "anchors": {0: "a", 1: "b", 2: "c", 3: "d"},  # no 4
                }
            ]
        )


def test_blank_anchor_fails_to_load():
    with pytest.raises(RubricError, match="empty anchors"):
        _rubric(
            dimensions=[
                {
                    "key": "k",
                    "name": "n",
                    "description": "d",
                    "concept_bearing": True,
                    "anchors": {0: "a", 1: "  ", 2: "c", 3: "d", 4: "e"},
                }
            ]
        )


# ── concept_bearing (FR-13.22, AC-13.18) ─────────────────────────────────


@pytest.mark.gate
def test_zero_concept_bearing_dimensions_fails_to_load():
    with pytest.raises(RubricError, match="concept-bearing"):
        _rubric(
            dimensions=[
                {
                    "key": "k",
                    "name": "n",
                    "description": "d",
                    "anchors": {i: "x" for i in range(5)},
                }
            ]
        )


@pytest.mark.gate
def test_two_concept_bearing_dimensions_fails_to_load():
    """Never a runtime decision.

    The runtime default would be a weighted mean, which folds communication
    into technical mastery — a value nobody chose and nobody can untangle
    afterwards, because by then it is in θ.
    """
    dims = [
        {
            "key": key,
            "name": key,
            "description": "d",
            "concept_bearing": True,
            "anchors": {i: "x" for i in range(5)},
        }
        for key in ("a", "b")
    ]
    with pytest.raises(RubricError, match="concept-bearing"):
        _rubric(dimensions=dims)


# ── hint penalty (§6.1) ──────────────────────────────────────────────────


def test_hint_credit_must_not_increase_with_help():
    with pytest.raises(RubricError, match="never credit more"):
        _rubric(hint_penalty={0: 0.5, 1: 0.9})


def test_hint_credit_must_be_a_fraction():
    with pytest.raises(RubricError, match=r"\(0, 1\]"):
        _rubric(hint_penalty={0: 1.5})


def test_unlisted_hint_level_credits_fully():
    assert _rubric().credit(9) == 1.0


# ── applies_when (§6.1) ──────────────────────────────────────────────────


def test_unknown_applies_when_field_fails_to_load():
    with pytest.raises(RubricError):
        _rubric(
            dimensions=[
                {
                    "key": "k",
                    "name": "n",
                    "description": "d",
                    "concept_bearing": True,
                    "anchors": {i: "x" for i in range(5)},
                    "applies_when": {"field": "phase_of_moon", "op": "eq", "value": "full"},
                }
            ]
        )


def test_applies_when_filters_dimensions():
    dims = [
        {
            "key": "always",
            "name": "n",
            "description": "d",
            "concept_bearing": True,
            "anchors": {i: "x" for i in range(5)},
        },
        {
            "key": "coding_only",
            "name": "n",
            "description": "d",
            "anchors": {i: "x" for i in range(5)},
            "applies_when": {"field": "modality", "op": "eq", "value": "coding"},
        },
    ]
    rubric = _rubric(dimensions=dims)
    assert [d.key for d in rubric.applicable({"modality": "verbal"})] == ["always"]
    assert len(rubric.applicable({"modality": "coding"})) == 2


def test_applies_when_op_and_value_must_agree():
    with pytest.raises(ValueError, match="takes a list"):
        AppliesWhen(field="modality", op="in", value="coding")


def test_dimension_weight_must_be_positive():
    with pytest.raises(ValueError):
        RubricDimension(
            key="k",
            name="n",
            description="d",
            anchors={i: "x" for i in range(5)},
            weight=0,
        )

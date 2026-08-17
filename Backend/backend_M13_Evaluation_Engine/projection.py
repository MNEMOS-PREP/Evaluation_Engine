"""The blind projection — spec §6.2.

The evaluator sees the question, the reference answer, the key points, the
rubric and the answer. It does not see who the candidate is, what they scored
before, what the interviewer was thinking, or any other turn. Each of those
omissions counters a named bias — anchoring, halo, leniency contagion — and
together they are why `Evaluator` is a separate agent at all.

**The enforcement is the type, not the prompt.** `leaks_identity()` walks a
view's type graph and reports any path that reaches a forbidden type. It runs
in CI as AC-13.2, and it is exact — a graph walk is deterministic in a way
that a counterfactual score comparison can never be (which is why AC-13.3 is a
statistical gate and this one is not).

Two rules follow from having the test rather than the convention:

**Rubric selection is the caller's, and the evaluator never learns why.** A
steelman turn — M6 stores it as `deliberately_false=True` — is dispatched by
M6 against the `push_back` rubric variant. The evaluator sees question +
reference + rubric + answer exactly as always, and the rubric it happens to be
holding is the one whose dimensions are about disagreement. Nothing leaks,
because "which rubric am I applying" is not "what was the interviewer
thinking" (EC-13.10).

**Comparators are anonymised.** §6.5 wants to compare a candidate against
their own past work, which is where "you vs you three months ago" comes from.
A prior `Turn` in the view would reach `Candidate` in one hop and fail the
test above, so a comparator crosses the boundary as bare text and a band.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Literal

from pydantic import BaseModel, Field

from .contracts import Rubric

#: Names a projection's type graph may never reach. Matched on the class name
#: so the check does not need to import modules that may not exist yet (M04's
#: `Mastery`, M06's `SessionState`), which is the point — a view that grows a
#: field pointing at a future module still fails the day the field lands.
FORBIDDEN_TYPE_NAMES = frozenset(
    {
        "Candidate",
        "CandidateProfile",
        "Profile",
        "Turn",
        "TurnEvaluation",
        "Mastery",
        "Observation",
        "SessionState",
        "InterviewerView",
        "HumanRating",
    }
)

#: Field names that carry identity even when their type is innocuous. A
#: `candidate_id: UUID` reaches nothing in the type graph and leaks everything.
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "candidate_id",
        "candidate",
        "candidate_name",
        "student_id",
        "student_name",
        "roll_number",
        "name",
        "full_name",
        "email",
        "profile",
        "theta",
        "mastery",
        "prior_scores",
        "prior_score",
        "probe_intent",
        "interviewer_reasoning",
        "deliberately_false",
        "session_id",
        "timestamps",
        "evaluated_at",
    }
)

#: Types that are module CONFIGURATION rather than candidate data, and are
#: therefore exempt from the field-name check (never from the type check).
#:
#: This allowlist exists because `name` has to stay forbidden — a field
#: literally called `name` holding a student's name is the exact leak this
#: guards — while a rubric dimension's display name is authored by the team
#: and contains nothing about anybody. Keeping the exemption as an explicit,
#: short, testable list is the honest way to have both: `test_projection`
#: asserts it stays small, so the escape hatch cannot quietly grow into one
#: that covers a type carrying real candidate data.
SAFE_CONFIG_TYPE_NAMES = frozenset(
    {
        "Rubric",
        "RubricDimension",
        "Disqualifier",
        "AppliesWhen",
        "KeyPoint",
        "ComparatorText",
    }
)


class KeyPoint(BaseModel):
    """M5's type, as far as the evaluator needs it."""

    id: str
    statement: str
    weight: float = 1.0
    required: bool = False


class EvaluatorView(BaseModel):
    """Everything the evaluator is allowed to know.

    Every absent field below is absent on purpose; see the module docstring.
    """

    question_stem: str
    reference_answer: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    rubric: Rubric
    answer_text: str
    #: Present only for coding rounds; the caller decides, not the evaluator.
    code: str | None = None
    canvas: str | None = None
    #: The NLI scaffold (§6.4 step 1), when it ran. Its presence is recorded
    #: on the evaluation as `scaffold_used`, because it changes the measurement.
    key_point_coverage: dict[str, float] | None = None

    # DELIBERATELY ABSENT: candidate_id, name, gender-coded anything, profile,
    # theta, prior scores, interviewer reasoning, probe_intent, other turns,
    # session metadata, timestamps.


class ComparatorText(BaseModel):
    """A comparator, stripped of everything that could identify its author.

    Whether this is a reference answer or the student's own past work is held
    by the caller and never crosses the boundary — which is what lets §6.5
    compare a candidate against themselves without the pairwise path failing
    AC-13.2.
    """

    text: str
    quality_band: Literal[0, 1, 2, 3, 4]


class PairwiseView(BaseModel):
    """The weakly-absolute path (§6.5, Phase 2). Its own view, its own gate."""

    question_stem: str
    rubric: Rubric
    dimension_key: str
    answer_text: str
    comparators: list[ComparatorText] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────
#  The architectural test (AC-13.2)
# ─────────────────────────────────────────────────────────────────────────


def _unwrap(annotation: Any) -> list[Any]:
    """Flatten Optional/Union/list/dict annotations into their member types."""
    origin = typing.get_origin(annotation)
    if origin is None:
        return [annotation]
    if origin in (typing.Union, types.UnionType):
        return [a for arg in typing.get_args(annotation) for a in _unwrap(arg)]
    return [a for arg in typing.get_args(annotation) for a in _unwrap(arg)]


def leaks_identity(model: type[BaseModel]) -> list[str]:
    """Every path from `model` that reaches something the evaluator must not see.

    Returns a list of human-readable paths, empty when the view is clean. A
    list rather than a bool because the failure message is the whole value:
    "EvaluatorView.turn.candidate_id" tells you what to delete, and
    "leaks: True" starts an investigation.
    """
    findings: list[str] = []
    seen: set[type] = set()

    def walk(current: type[BaseModel], path: str) -> None:
        if current in seen:
            return
        seen.add(current)

        is_config = current.__name__ in SAFE_CONFIG_TYPE_NAMES

        for field_name, field in current.model_fields.items():
            here = f"{path}.{field_name}"

            # Configuration types are exempt from the NAME check only. They are
            # still walked for forbidden TYPES below, so a rubric that grew a
            # field pointing at a candidate still fails.
            if not is_config and field_name in FORBIDDEN_FIELD_NAMES:
                findings.append(f"{here} — forbidden field name")
                continue

            for candidate in _unwrap(field.annotation):
                if not isinstance(candidate, type):
                    continue
                if candidate.__name__ in FORBIDDEN_TYPE_NAMES:
                    findings.append(f"{here}: {candidate.__name__} — forbidden type")
                    continue
                if issubclass(candidate, BaseModel):
                    walk(candidate, here)

    walk(model, model.__name__)
    return findings


def assert_blind(model: type[BaseModel]) -> None:
    """Raise unless the view is blind. The enforcement AC-13.2 calls."""
    leaks = leaks_identity(model)
    if leaks:
        raise AssertionError(
            f"{model.__name__} can reach candidate identity:\n  "
            + "\n  ".join(leaks)
            + "\n\nThis is AC-13.2. The prompt is not the enforcement; this is."
        )


# ─────────────────────────────────────────────────────────────────────────
#  Builders
# ─────────────────────────────────────────────────────────────────────────


def project_for_evaluator(
    *,
    question_stem: str,
    reference_answer: str,
    key_points: list[KeyPoint],
    rubric: Rubric,
    answer_text: str,
    code: str | None = None,
    canvas: str | None = None,
    key_point_coverage: dict[str, float] | None = None,
) -> EvaluatorView:
    """Build the view. Keyword-only, so nothing is passed positionally by accident.

    `code` and `canvas` are gated by the ROUND TYPE rather than by whether the
    caller happens to have them, because "the evaluator sees the code buffer
    only in a coding round" is a property of the rubric, not of the plumbing.
    """
    is_coding = rubric.round_type.endswith("coding")
    is_design = rubric.round_type == "system_design"
    return EvaluatorView(
        question_stem=question_stem,
        reference_answer=reference_answer,
        key_points=key_points,
        rubric=rubric,
        answer_text=answer_text,
        code=code if is_coding else None,
        canvas=canvas if is_design else None,
        key_point_coverage=key_point_coverage,
    )


def project_for_pairwise(
    *,
    question_stem: str,
    rubric: Rubric,
    dimension_key: str,
    answer_text: str,
    comparators: list[ComparatorText],
) -> PairwiseView:
    return PairwiseView(
        question_stem=question_stem,
        rubric=rubric,
        dimension_key=dimension_key,
        answer_text=answer_text,
        comparators=list(comparators),
    )


__all__ = [
    "ComparatorText",
    "EvaluatorView",
    "KeyPoint",
    "PairwiseView",
    "assert_blind",
    "leaks_identity",
    "project_for_evaluator",
    "project_for_pairwise",
]

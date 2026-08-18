"""The structured-output schema handed to the evaluator — spec §6.4 step 3.

Two constraints in here are load-bearing, and both are consequences of what
structured outputs can and cannot express.

**`raw_score` is an `enum`, not `{"type":"integer","minimum":0,"maximum":4}`.**
Structured outputs do not support numeric constraints — `minimum`, `maximum`
and `multipleOf` are stripped from the schema — so the range form silently
accepts a `7`, cleanly typed and out of range. EC-13.12 says an out-of-range
score is a "schema rejection"; `enum` is what makes that true rather than
aspirational.

**`artifact_id` is an `enum` of this turn's artifacts.** The same trick M15
uses for grounding claim ids (`IMPLEMENTATION_PLAN.md` §B.4): a value the
model invented cannot be returned at all, which is strictly better than
catching it downstream. Offsets still have to be verified — the model can
point at a real artifact and still get the range wrong — but it removes one
whole class of unresolvable evidence before it exists.

Everything is `additionalProperties: false` with every field `required`,
because a partially-filled score is harder to reason about than a missing one.
"""

from __future__ import annotations

from uuid import UUID

from .contracts import SCALE_MAX, SCALE_MIN, Rubric, RubricDimension

PROMPT_VERSION = "m13-eval-1.0.0"


def _span_schema(artifact_ids: list[UUID]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["artifact_id", "start", "end", "quote"],
        "properties": {
            "artifact_id": {
                "type": "string",
                # A hallucinated artifact id is structurally impossible.
                "enum": [str(a) for a in artifact_ids],
            },
            "start": {"type": "integer"},
            "end": {"type": "integer"},
            "quote": {
                "type": "string",
                "description": (
                    "Verbatim text from the artifact between start and end. "
                    "It is checked character-for-character against the artifact; "
                    "a paraphrase is rejected."
                ),
            },
        },
    }


def _dimension_schema(dimensions: list[RubricDimension], artifact_ids: list[UUID]) -> dict:
    """ONE item schema covering every dimension, not one variant per dimension.

    The earlier shape was an `anyOf` of per-dimension objects, each pinning
    `dimension_key` to a single-value enum so the anchors could ride along in
    that variant's `raw_score` description. It was too clever and it did not
    survive contact with a second provider: Groq rejects it outright —

        anyOf disambiguation failed: multiple candidate properties
        dimension_key, raw_score [discriminator_multiple_candidates]

    — because both properties are enums and neither is an obvious
    discriminator. One uniform object with `dimension_key` enumerated over all
    the keys is portable, and it loses nothing: the anchors are already in the
    prompt in full, which is where a model actually reads them.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "dimension_key",
            "raw_score",
            "reasoning",
            "evidence",
            "missing_key_points",
            "model_confidence",
        ],
        "properties": {
            "dimension_key": {"type": "string", "enum": [d.key for d in dimensions]},
            "raw_score": {
                "type": "integer",
                # NOT minimum/maximum — structured outputs drop those.
                "enum": list(range(SCALE_MIN, SCALE_MAX + 1)),
                "description": (
                    "The anchored level for this dimension, 0-4. The anchors are "
                    "in the RUBRIC block of the message; use them literally."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One or two sentences a STUDENT will read, naming what was "
                    "present and what was missing. Not a restatement of the score."
                ),
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "items": _span_schema(artifact_ids),
                "description": (
                    "At least one verbatim span from the candidate's own answer "
                    "that justifies this score."
                ),
            },
            "missing_key_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "model_confidence": {"type": "number"},
        },
    }


def evaluator_schema(
    rubric: Rubric,
    artifact_ids: list[UUID],
    *,
    context: dict | None = None,
    only: list[str] | None = None,
) -> dict:
    """The JSON schema for one evaluator call.

    `only` narrows it to the contested dimensions for the adjudicator, so it
    re-decides what was disputed and does not re-litigate what everyone agreed
    on — that would be a different measurement wearing the same name.
    """
    dimensions = rubric.applicable(context or {})
    if only is not None:
        wanted = set(only)
        dimensions = [d for d in dimensions if d.key in wanted]
    disqualifier_keys = [d.key for d in rubric.disqualifiers]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scores", "overall_note", "disqualifiers_triggered"],
        "properties": {
            "scores": {
                "type": "array",
                # Exactly one score per applicable dimension — the count is
                # what stops a model answering only the easy ones.
                "minItems": len(dimensions),
                "maxItems": len(dimensions),
                "items": _dimension_schema(dimensions, artifact_ids),
            },
            "overall_note": {"type": "string"},
            "disqualifiers_triggered": {
                "type": "array",
                # Empty enum would be invalid; omit the constraint when the
                # rubric declares none.
                "items": (
                    {"type": "string", "enum": disqualifier_keys}
                    if disqualifier_keys
                    else {"type": "string"}
                ),
            },
        },
    }


__all__ = ["PROMPT_VERSION", "evaluator_schema"]

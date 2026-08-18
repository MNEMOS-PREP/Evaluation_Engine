"""The ensemble — spec §6.4 steps 3–5. Milestone M4.

Three independent evaluations, a median, and an adjudicator when they
disagree. The parts that are easy to get wrong, in the order they bite:

**Independence is not free on these models.** `claude-sonnet-5` and
`claude-opus-5` reject `temperature`, `top_p` and `top_k` — the parameters
were removed. So three calls to one model with the same bytes are one sample
three times: `spread` collapses to zero, adjudication never fires, and the
badge reports determinism as agreement. Every member therefore gets a
different `dimension_order_seed`, and the default config is heterogeneous.
`homogeneous_without_decorrelation()` exists so a config that would lie about
its own confidence can be rejected rather than merely discouraged (FR-13.26).

**Median, not mean.** With N=3 on an ordinal scale the median is the level a
majority would accept; a mean invents a 2.67 that no anchor describes and that
no rater could have given.

**Spread is `max − min`, an integer.** One definition, everywhere (§6.4). The
earlier draft called it σ in one place and range in another, and on a 0–4
scale with N=3 those disagree on cases that occur constantly.

**Evidence is unioned, not taken from the winner.** Three evaluators quoting
three different lines is more evidence for the student, not less — deduped by
overlap and capped, because an evidence drawer with nine quotes is a wall.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median_low

from ai_core.evidence import EvidenceRef

from .contracts import Agreement, DimensionScore, EvaluatorOutput
from .evaluator import EvaluationRequest, evaluate_once
from .llm import JOB_ADJUDICATE, LLM, get_llm

log = logging.getLogger(__name__)

#: §6.4 step 5 — adjudicate when any dimension is this far apart.
ADJUDICATION_THRESHOLD = 2

#: §6.4 step 4 — an evidence drawer is a reading surface, not an archive.
MAX_SPANS_PER_DIMENSION = 3


@dataclass(frozen=True)
class Member:
    """One seat in the ensemble."""

    #: Which model tier answers. `None` means "whatever `get_llm()` resolves",
    #: which is what the free-tier dev path uses.
    model: str | None = None
    #: The decorrelating permutation. MUST differ between same-model members.
    seed: int = 0


@dataclass(frozen=True)
class EnsembleConfig:
    """A named ensemble. The name is part of the calibration key (§6.7)."""

    name: str
    members: tuple[Member, ...]

    @property
    def size(self) -> int:
        return len(self.members)

    def homogeneous_without_decorrelation(self) -> bool:
        """True when two members would send identical bytes to the same model.

        That is not an ensemble, and the confidence badge built on it would be
        reporting determinism. Checked rather than trusted (FR-13.26).
        """
        seen: set[tuple[str | None, int]] = set()
        for member in self.members:
            key = (member.model, member.seed)
            if key in seen:
                return True
            seen.add(key)
        return False


#: §6.4's default: heterogeneity is mandatory, not budget-permitting, and the
#: two same-tier members are decorrelated by a rubric-neutral permutation.
N3_HETEROGENEOUS = EnsembleConfig(
    name="n3_het_v1",
    members=(Member(model=None, seed=0), Member(model=None, seed=17), Member(model=None, seed=41)),
)

#: Practice mode and the degradation ladder (M6 §26.6). Drops the COUNT, never
#: the tier — and its scores are calibrated separately or not displayed (§6.7).
N1_PRACTICE = EnsembleConfig(name="n1_practice", members=(Member(model=None, seed=0),))

CONFIGS = {c.name: c for c in (N3_HETEROGENEOUS, N1_PRACTICE)}


class InvalidEnsemble(ValueError):
    """A configuration that would misreport its own confidence."""


@dataclass
class EnsembleResult:
    outputs: list[EvaluatorOutput] = field(default_factory=list)
    aggregated: list[DimensionScore] = field(default_factory=list)
    spread_levels: dict[str, int] = field(default_factory=dict)
    agreement: dict[str, Agreement] = field(default_factory=dict)
    adjudicated: bool = False
    adjudication_note: str | None = None

    @property
    def usable(self) -> list[EvaluatorOutput]:
        return [o for o in self.outputs if o.ok]


def agreement_for(spread: int, *, members: int) -> Agreement:
    """What the badge shows.

    A single evaluator is never "high" — one evaluator agreeing with itself is
    not evidence, and §8.1 forbids rendering it as though it were.
    """
    if members < 2:
        return Agreement.medium
    if spread >= ADJUDICATION_THRESHOLD:
        return Agreement.low
    return Agreement.high if spread == 0 else Agreement.medium


def _merge_evidence(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Union, deduped by overlap, capped. Longest span wins a collision."""
    ordered = sorted(
        refs,
        key=lambda r: -((r.span.end - r.span.start) if r.span else 0),
    )
    kept: list[EvidenceRef] = []
    for ref in ordered:
        if ref.span is None:
            continue
        if any(
            k.span is not None
            and k.span.artifact_id == ref.span.artifact_id
            and ref.span.start < k.span.end
            and ref.span.end > k.span.start
            for k in kept
        ):
            continue
        kept.append(ref)
        if len(kept) >= MAX_SPANS_PER_DIMENSION:
            break
    # Read in document order — the drawer is a transcript, not a ranking.
    return sorted(kept, key=lambda r: (str(r.span.artifact_id), r.span.start))  # type: ignore[union-attr]


def aggregate(outputs: list[EvaluatorOutput]) -> EnsembleResult:
    """Median per dimension, spread as max − min, evidence unioned."""
    result = EnsembleResult(outputs=list(outputs))
    usable = result.usable
    if not usable:
        return result

    by_dimension: dict[str, list[DimensionScore]] = {}
    for output in usable:
        for score in output.scores:
            by_dimension.setdefault(score.dimension_key, []).append(score)

    for key, scores in by_dimension.items():
        raws = [s.raw_score for s in scores]
        spread = max(raws) - min(raws)
        merged = _merge_evidence([ref for s in scores for ref in s.evidence])

        # The reasoning shown is the one from the member whose score IS the
        # median — a merged paragraph would be a sentence nobody wrote about a
        # score nobody gave.
        chosen_raw = median_low(raws)
        speaker = next(s for s in scores if s.raw_score == chosen_raw)

        result.aggregated.append(
            DimensionScore(
                dimension_key=key,
                raw_score=chosen_raw,
                evidence=merged,
                reasoning=speaker.reasoning,
                missing_key_points=sorted({kp for s in scores for kp in s.missing_key_points}),
                model_confidence=sum(s.model_confidence for s in scores) / len(scores),
                disqualifiers_triggered=sorted(
                    {d for s in scores for d in s.disqualifiers_triggered}
                ),
            )
        )
        result.spread_levels[key] = spread
        result.agreement[key] = agreement_for(spread, members=len(usable))

    result.aggregated.sort(key=lambda s: s.dimension_key)
    return result


def run(
    request: EvaluationRequest,
    config: EnsembleConfig = N3_HETEROGENEOUS,
    *,
    llm: LLM | None = None,
) -> EnsembleResult:
    """Run every member, then aggregate. Members are independent by construction.

    Sequential rather than concurrent on purpose for now: the free tier this
    develops against is rate-limited per minute, and three parallel calls just
    means three 429s instead of three answers. Parallelising is a change to
    this function alone when the budget allows.
    """
    if config.homogeneous_without_decorrelation():
        raise InvalidEnsemble(
            f"ensemble '{config.name}' has two members with the same model and seed. "
            "These models take no sampling parameter, so those two calls are one "
            "sample twice — spread would collapse to 0 and the confidence badge "
            "would be reporting determinism (FR-13.26)."
        )

    client = llm or get_llm()
    outputs: list[EvaluatorOutput] = []
    for index, member in enumerate(config.members):
        member_request = EvaluationRequest(
            view=request.view,
            artifacts=request.artifacts,
            session_id=request.session_id,
            turn_id=request.turn_id,
            evaluator_index=index,
            dimension_order_seed=member.seed,
            context=request.context,
        )
        outputs.append(evaluate_once(member_request, llm=client))

    return aggregate(outputs)


def needs_adjudication(result: EnsembleResult) -> bool:
    return any(spread >= ADJUDICATION_THRESHOLD for spread in result.spread_levels.values())


ADJUDICATOR_PROMPT = """\
Two or more independent evaluators scored the same answer and disagreed by at
least two levels on a rubric dimension. Reconcile it.

You are given the same blind view they had — the question, the reference
answer, the rubric, and the candidate's answer — plus what each of them said.
You are NOT told who the candidate is or which evaluator is which model.

RULES

1. Pick the level whose anchor matches what the candidate actually did. You
   may pick a level none of them chose.

2. Explain the disagreement in one or two sentences, in terms of the anchors:
   what one evaluator counted that the other did not. This note is shown to
   the student when confidence is low, so write it for them.

3. Cite at least one verbatim span, exactly as the evaluators had to. It is
   checked character-for-character.
"""


def adjudicate(
    request: EvaluationRequest,
    result: EnsembleResult,
    *,
    llm: LLM | None = None,
) -> EnsembleResult:
    """Frontier-tier reconciliation of a genuine disagreement (§6.4 step 5).

    Only the disagreeing dimensions are re-decided. A dimension all three
    agreed on is not re-litigated by a fourth opinion — that would be a
    different measurement wearing the same name.
    """
    contested = [k for k, s in result.spread_levels.items() if s >= ADJUDICATION_THRESHOLD]
    if not contested:
        return result

    client = llm or get_llm()
    transcript = "\n\n".join(
        f"EVALUATOR {o.evaluator_index}\n"
        + "\n".join(
            f"  [{s.dimension_key}] {s.raw_score} — {s.reasoning}"
            for s in o.scores
            if s.dimension_key in contested
        )
        for o in result.usable
    )

    sub_request = EvaluationRequest(
        view=request.view,
        artifacts=request.artifacts,
        session_id=request.session_id,
        turn_id=request.turn_id,
        evaluator_index=99,
        context=request.context,
    )
    verdict = evaluate_once(
        sub_request,
        llm=client,
        system_prompt=ADJUDICATOR_PROMPT,
        extra_context=f"WHAT THE EVALUATORS SAID\n{transcript}",
        job=JOB_ADJUDICATE,
        only_dimensions=contested,
    )

    if not verdict.ok:
        log.warning("adjudication failed (%s); keeping the median", verdict.dropped_reason)
        return result

    by_key = {s.dimension_key: s for s in verdict.scores}
    for i, score in enumerate(result.aggregated):
        replacement = by_key.get(score.dimension_key)
        if replacement is not None:
            result.aggregated[i] = replacement

    result.outputs.append(verdict)
    result.adjudicated = True
    result.adjudication_note = verdict.overall_note or (
        "Two evaluators read this differently; a third reconciled it."
    )
    for key in contested:
        result.agreement[key] = Agreement.low
    return result


__all__ = [
    "ADJUDICATION_THRESHOLD",
    "CONFIGS",
    "N1_PRACTICE",
    "N3_HETEROGENEOUS",
    "EnsembleConfig",
    "EnsembleResult",
    "InvalidEnsemble",
    "Member",
    "adjudicate",
    "aggregate",
    "agreement_for",
    "needs_adjudication",
    "run",
]

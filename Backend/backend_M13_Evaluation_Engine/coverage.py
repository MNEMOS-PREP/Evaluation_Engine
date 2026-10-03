"""Key-point coverage — spec §6.4 step 1. Milestone M5.

For each key point, does the answer entail it? The spec calls for a local
DeBERTa-v3-MNLI at ~180ms. That model is a ~750MB download, so it lives behind
an adapter: if `transformers` and the weights are present the real entailment
model runs, and otherwise a lexical fallback does. Both are honest about which
they were, because the calibration corpus has to know.

**Two things this measure is NOT, and both are easy to get wrong.**

It is not independent of the score once it is shown to the evaluator. The
moment the coverage vector goes into the prompt, the evaluator's judgement is
conditioned on it — so `scaffold_used` is recorded on every evaluation and the
calibration fit stratifies on it (§6.4). Otherwise the corpus quietly spans two
different measurements.

And it is not a scoring signal on its own. It produces `missing_key_points`,
which is the ✓/✗ checklist a student reads — the thing that turns a score into
a study plan. The number still comes from the rubric.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from .contracts import KP_ENTAILMENT_THRESHOLD, KP_LEXICAL_ABSENT_BELOW
from .projection import KeyPoint

log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("M13_NLI_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")

_WORD = re.compile(r"[a-z0-9]+")
#: Words that carry no evidence of understanding. Deliberately short: an
#: aggressive stoplist is how a lexical measure starts flattering short answers.
_STOP = frozenset(
    """a an the is are was were be been being of to in on at for with by from as
    it its this that these those and or but if then so than there here you your
    i we they he she do does did done have has had not no yes can could would
    should will shall may might must about into over under more most less"""
    .split()
)


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


@dataclass
class Coverage:
    """Per key point, how well the answer covers it."""

    scores: dict[str, float] = field(default_factory=dict)
    method: str = "none"

    @property
    def available(self) -> bool:
        return self.method != "none"

    def missing(self, threshold: float | None = None) -> list[str]:
        """Key points the answer did not cover, by this measure's own bar.

        The lexical fallback counts shared words, not meaning, so it may only
        call a point missing when almost none of its words are there — at the
        entailment bar it flagged every paraphrase, and the student read
        "not covered" under an answer the evaluator called complete.
        """
        if threshold is None:
            lexical = self.method == "lexical"
            threshold = KP_LEXICAL_ABSENT_BELOW if lexical else KP_ENTAILMENT_THRESHOLD
        return sorted(k for k, v in self.scores.items() if v < threshold)


class CoverageModel(Protocol):
    name: str

    def entail(self, premise: str, hypotheses: list[str]) -> list[float]: ...


@dataclass
class LexicalCoverage:
    """The fallback: proportion of a key point's content words that appear.

    Crude, and labelled crude. It is genuinely useful for the checklist — a key
    point whose every content word is absent was almost certainly not covered —
    and genuinely unfit for the paper, which is why `method` travels with the
    numbers rather than being assumed.
    """

    name: str = "lexical"

    def entail(self, premise: str, hypotheses: list[str]) -> list[float]:
        have = _terms(premise)
        out = []
        for hypothesis in hypotheses:
            want = _terms(hypothesis)
            out.append(len(want & have) / len(want) if want else 0.0)
        return out


@dataclass
class NliCoverage:
    """The real thing: DeBERTa-v3-MNLI, local, no network at inference."""

    name: str = "nli"
    _pipe: object | None = field(default=None, repr=False)

    def entail(self, premise: str, hypotheses: list[str]) -> list[float]:
        pipe = self._pipeline()
        out = []
        for hypothesis in hypotheses:
            result = pipe(premise, candidate_labels=[hypothesis], multi_label=True)  # type: ignore[operator]
            out.append(float(result["scores"][0]))
        return out

    def _pipeline(self) -> object:
        if self._pipe is None:
            from transformers import pipeline  # noqa: PLC0415 — heavy, optional

            self._pipe = pipeline("zero-shot-classification", model=MODEL_NAME)
        return self._pipe


@lru_cache(maxsize=1)
def get_model() -> CoverageModel:
    """The entailment model if it is installed, otherwise the lexical fallback.

    Never raises and never blocks on a download: a missing optional dependency
    degrades the checklist's precision, which §10 already says it does, and
    must not take an evaluation with it.
    """
    if os.getenv("M13_DISABLE_NLI", "").strip():
        return LexicalCoverage()
    try:
        import transformers  # noqa: F401, PLC0415

        model = NliCoverage()
        model.entail("warm up", ["warm up"])  # fail here, not mid-evaluation
        log.info("key-point coverage: %s", MODEL_NAME)
        return model
    except Exception as exc:  # noqa: BLE001 — any failure means fall back
        log.info("key-point coverage: lexical fallback (%s)", type(exc).__name__)
        return LexicalCoverage()


def reload() -> None:
    get_model.cache_clear()


def score(
    answer: str, key_points: list[KeyPoint], *, model: CoverageModel | None = None
) -> Coverage:
    if not key_points:
        return Coverage(method="none")
    engine = model or get_model()
    values = engine.entail(answer, [kp.statement for kp in key_points])
    return Coverage(
        scores={kp.id: round(v, 4) for kp, v in zip(key_points, values, strict=True)},
        method=engine.name,
    )


__all__ = [
    "Coverage",
    "CoverageModel",
    "LexicalCoverage",
    "NliCoverage",
    "get_model",
    "reload",
    "score",
]

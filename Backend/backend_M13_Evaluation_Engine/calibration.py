"""Calibration and the display gate — spec §6.6, §6.7. Milestone M9.

Raw model scores are not human scores. This module fits the mapping between
them and, more importantly, decides whether the result is good enough to show
a student a number at all.

**The gate is the point, not the mapping.** §2.4's promise is that a dimension
we cannot score accurately shows qualitative feedback and no number, and says
so out loud. `evaluate_gate()` is that promise as a function: five conditions,
each with a reason string a human can read, resolved at render time from the
fitted model rather than hardcoded anywhere.

**Keyed on `ensemble_config`.** A median of three is a different estimator from
a single draw, so a mapping fitted on one does not describe the other. Without
this, a Practice-mode score silently borrows the confidence of a full ensemble
(Trap 10).

No numpy, no sklearn, no scipy. Everything here is a few dozen lines of
arithmetic, it runs in CI with no wheels to install, and the alternative is a
dependency that has to be present on a marker's laptop for the module to
start. Fitting 800 items is milliseconds either way.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import mean

from .contracts import SCALE_MAX, SCALE_MIN

log = logging.getLogger(__name__)

# ── Gate thresholds (§6.7) ───────────────────────────────────────────────

QWK_OVERALL_MIN = 0.70
QWK_DIMENSION_MIN = 0.60
LENGTH_BIAS_MAX = 0.15
ECE_MAX = 0.10
#: Below this many rated items a fit is noise wearing a coefficient.
MIN_FIT_N = 30


@dataclass
class Pair:
    """One model score against the human score it is being calibrated to.

    `human` is the MFRM severity-corrected value where available — §6.6 is
    explicit that calibrating to raw rater means calibrating to whichever
    raters were recruited.
    """

    raw: int
    human: float
    #: Answer length in tokens, for the length-bias covariate (§6.7).
    length_tokens: int = 0
    model_confidence: float = 0.0
    correct: bool = False


# ─────────────────────────────────────────────────────────────────────────
#  Metrics
# ─────────────────────────────────────────────────────────────────────────


def quadratic_weighted_kappa(a: list[int], b: list[int]) -> float:
    """QWK — the standard for ordinal automated-scoring agreement.

    Quadratic weights because on an anchored scale a two-level miss is much
    worse than two one-level misses, and linear weights say they are the same.
    """
    if not a or len(a) != len(b):
        return 0.0
    levels = list(range(SCALE_MIN, SCALE_MAX + 1))
    n = len(levels)
    index = {lvl: i for i, lvl in enumerate(levels)}

    observed = [[0.0] * n for _ in range(n)]
    for x, y in zip(a, b, strict=True):
        observed[index[_clamp_level(x)]][index[_clamp_level(y)]] += 1

    hist_a = [sum(row) for row in observed]
    hist_b = [sum(observed[i][j] for i in range(n)) for j in range(n)]
    total = float(len(a))

    num = den = 0.0
    for i in range(n):
        for j in range(n):
            weight = ((i - j) ** 2) / ((n - 1) ** 2)
            expected = hist_a[i] * hist_b[j] / total
            num += weight * observed[i][j]
            den += weight * expected
    return 1.0 - num / den if den else 0.0


def _clamp_level(value: float) -> int:
    return max(SCALE_MIN, min(SCALE_MAX, int(round(value))))


def krippendorff_alpha(ratings: dict[str, list[int]]) -> float:
    """Ordinal α across raters, keyed by item. The ceiling we are chasing.

    Handles missing ratings by construction — an item one rater skipped still
    contributes the pairs that exist, which is exactly why §6.6 chose α over a
    kappa that needs a complete matrix.
    """
    pairs: list[tuple[int, int]] = []
    for values in ratings.values():
        for i, first in enumerate(values):
            for second in values[i + 1 :]:
                pairs.extend([(first, second), (second, first)])
    if not pairs:
        return 0.0

    observed = mean(((x - y) ** 2) for x, y in pairs)
    everything = [v for values in ratings.values() for v in values]
    expected = mean(
        ((x - y) ** 2) for i, x in enumerate(everything) for y in everything[i + 1 :]
    ) if len(everything) > 1 else 0.0
    return 1.0 - observed / expected if expected else 0.0


def expected_calibration_error(pairs: list[Pair], bins: int = 10) -> float:
    """ECE on the evaluator's SELF-REPORTED confidence (AC-13.9).

    Deliberately not on ensemble agreement: agreement is what the badge shows,
    self-reported confidence is the research instrument, and conflating them
    was one of the review's findings.
    """
    usable = [p for p in pairs if p.model_confidence > 0]
    if not usable:
        return 1.0
    total = len(usable)
    error = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [
            p
            for p in usable
            if lo < p.model_confidence <= hi or (b == 0 and p.model_confidence == 0)
        ]
        if not bucket:
            continue
        confidence = mean(p.model_confidence for p in bucket)
        accuracy = mean(1.0 if p.correct else 0.0 for p in bucket)
        error += (len(bucket) / total) * abs(accuracy - confidence)
    return round(error, 4)


def length_bias_beta(pairs: list[Pair]) -> float:
    """Coefficient on log(length), in SCORE LEVELS per natural-log unit.

    The residual after the raw score is accounted for — we are asking whether
    length moves the score *beyond* what the humans also did, not whether long
    answers are ever better. Units matter here: the 0.15 gate is meaningless
    without them, which is why they are in the name and the docstring.
    """
    usable = [p for p in pairs if p.length_tokens > 0]
    if len(usable) < 3:
        return 0.0
    xs = [math.log(p.length_tokens) for p in usable]
    ys = [p.raw - p.human for p in usable]  # residual, not the score itself
    mx, my = mean(xs), mean(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denominator, 4)


# ─────────────────────────────────────────────────────────────────────────
#  Fitting
# ─────────────────────────────────────────────────────────────────────────


def fit_isotonic(pairs: list[Pair]) -> dict[int, float]:
    """Pool-adjacent-violators over the mean human score per raw level.

    Isotonic rather than a straight line because the relationship is
    monotonic-but-not-linear in practice: the gap between a 0 and a 1 is not
    the gap between a 3 and a 4. Monotonicity is enforced, because a
    calibration where a higher raw score maps to a lower human one is not a
    correction, it is a bug that would tell a student their better answer
    scored worse.
    """
    buckets: dict[int, list[float]] = {}
    for pair in pairs:
        buckets.setdefault(_clamp_level(pair.raw), []).append(pair.human)

    levels = sorted(buckets)
    values = [mean(buckets[lvl]) for lvl in levels]
    weights = [float(len(buckets[lvl])) for lvl in levels]

    i = 0
    while i < len(values) - 1:
        if values[i] <= values[i + 1]:
            i += 1
            continue
        pooled = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / (
            weights[i] + weights[i + 1]
        )
        values[i : i + 2] = [pooled]
        weights[i : i + 2] = [weights[i] + weights[i + 1]]
        levels[i : i + 2] = [levels[i]]
        i = max(i - 1, 0)

    # Re-expand to every observed raw level.
    out: dict[int, float] = {}
    for raw in sorted(buckets):
        chosen = 0
        for j, lvl in enumerate(levels):
            if lvl <= raw:
                chosen = j
        out[raw] = round(values[chosen], 4)
    return out


def apply_mapping(raw: int, params: dict) -> float:
    """Map a raw level through a fitted table.

    Accepts int OR str keys, because the table is int-keyed in memory and
    str-keyed once it has been through JSON — and a calibration that silently
    stopped applying after a round-trip through the database would be the
    worst kind of bug: every score would still look calibrated.
    """
    raw_table = params.get("table") or {}
    if not raw_table:
        return float(raw)
    table = {int(k): float(v) for k, v in raw_table.items()}
    level = _clamp_level(raw)
    if level in table:
        return table[level]
    nearest = min(table, key=lambda k: abs(k - level))
    return table[nearest]


# ─────────────────────────────────────────────────────────────────────────
#  The gate (§6.7)
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    display_numeric: bool
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def student_note(self) -> str | None:
        """§2.4's sentence, or None when a number is allowed."""
        if self.display_numeric:
            return None
        return (
            "We're not showing a number here yet — our scoring on this "
            "dimension isn't accurate enough to be worth a number."
        )


def evaluate_gate(
    *,
    n: int,
    qwk: float,
    qwk_overall: float,
    ece: float,
    beta: float,
    subgroup_gap: bool,
) -> GateResult:
    """Every condition §6.7 states, each with a reason a human can read.

    Reasons rather than a bare bool because "why is there no number on depth?"
    is a question a student, a faculty reviewer and an examiner all ask, and
    "the gate said no" is not an answer.
    """
    reasons: dict[str, str] = {}
    if n < MIN_FIT_N:
        reasons["sample"] = f"fitted on {n} items; {MIN_FIT_N} is the minimum"
    if qwk_overall < QWK_OVERALL_MIN:
        reasons["qwk_overall"] = f"overall QWK {qwk_overall:.2f} < {QWK_OVERALL_MIN}"
    if qwk < QWK_DIMENSION_MIN:
        reasons["qwk_dimension"] = f"dimension QWK {qwk:.2f} < {QWK_DIMENSION_MIN}"
    if abs(beta) >= LENGTH_BIAS_MAX:
        reasons["length_bias"] = (
            f"length bias {beta:+.2f} levels per log-token, limit ±{LENGTH_BIAS_MAX}"
        )
    if ece > ECE_MAX:
        reasons["ece"] = f"confidence ECE {ece:.2f} > {ECE_MAX}"
    if subgroup_gap:
        reasons["subgroup"] = "an unmitigated subgroup gap is open (§6.9)"
    return GateResult(display_numeric=not reasons, reasons=reasons)


@dataclass
class Fit:
    """The result of fitting one (dimension, round_type, ensemble_config)."""

    dimension_key: str
    round_type: str
    ensemble_config: str
    method: str
    params: dict
    n: int
    qwk: float
    qwk_overall: float
    alpha: float
    ece: float
    beta: float
    gate: GateResult
    scaffold_stratum: str = "pooled"


def fit(
    *,
    dimension_key: str,
    round_type: str,
    ensemble_config: str,
    pairs: list[Pair],
    qwk_overall: float | None = None,
    rater_ratings: dict[str, list[int]] | None = None,
    subgroup_gap: bool = False,
    scaffold_stratum: str = "pooled",
) -> Fit:
    """Fit the mapping and resolve the gate in one pass.

    Below `MIN_FIT_N` this deliberately still returns a `Fit` — with an
    identity mapping and a closed gate. A missing calibration and a failed one
    must be distinguishable: the first is "not measured yet", the second is
    "measured and not good enough", and only the second is a finding.
    """
    n = len(pairs)
    table = fit_isotonic(pairs) if n >= MIN_FIT_N else {}
    method = "isotonic" if table else "identity"

    predicted = [_clamp_level(apply_mapping(p.raw, {"table": table})) for p in pairs]
    humans = [_clamp_level(p.human) for p in pairs]
    qwk = quadratic_weighted_kappa(predicted, humans) if n else 0.0
    overall = qwk_overall if qwk_overall is not None else qwk
    ece = expected_calibration_error(pairs)
    beta = length_bias_beta(pairs)
    alpha = krippendorff_alpha(rater_ratings or {})

    gate = evaluate_gate(
        n=n, qwk=qwk, qwk_overall=overall, ece=ece, beta=beta, subgroup_gap=subgroup_gap
    )
    return Fit(
        dimension_key=dimension_key,
        round_type=round_type,
        ensemble_config=ensemble_config,
        method=method,
        params={"table": {str(k): v for k, v in table.items()}},
        n=n,
        qwk=round(qwk, 4),
        qwk_overall=round(overall, 4),
        alpha=round(alpha, 4),
        ece=ece,
        beta=beta,
        gate=gate,
        scaffold_stratum=scaffold_stratum,
    )


__all__ = [
    "ECE_MAX",
    "LENGTH_BIAS_MAX",
    "MIN_FIT_N",
    "QWK_DIMENSION_MIN",
    "QWK_OVERALL_MIN",
    "Fit",
    "GateResult",
    "Pair",
    "apply_mapping",
    "evaluate_gate",
    "expected_calibration_error",
    "fit",
    "fit_isotonic",
    "krippendorff_alpha",
    "length_bias_beta",
    "quadratic_weighted_kappa",
]

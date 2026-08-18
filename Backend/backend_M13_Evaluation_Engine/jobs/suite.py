"""Run the frozen suite against a real model — spec §6.10, §12.

    python -m backend_M13_Evaluation_Engine.jobs.suite

This is the harness the regression and adversarial suites run in. It is NOT a
pytest test and never will be: it needs a network and a key, and the rule that
no test in this repo opens a socket is worth more than the convenience.

**What a pass means depends entirely on `score_grade`.** On the free tier this
tells you whether the rubric anchors discriminate at all — which is the
question worth asking before anyone spends money. It is not evidence about the
production evaluator, and the report says so on every line rather than in a
footnote somebody scrolls past.

The number that matters here is not the pass rate. It is whether
`confidently_wrong` and `verbose_but_empty` land LOW while `terse_but_complete`
lands HIGH: that is the length-bias and fluency-bias question, and it is the
one an evaluator most commonly gets wrong.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

from .. import llm as llm_module
from ..adapters import get_questions, regression_cases
from ..keys import load_keys
from ..service import TurnInput, evaluate_turn


def _make_stdout_safe() -> None:
    """A model's output must not be able to crash the harness that reads it.

    Windows consoles default to cp1252, and models cheerfully emit non-breaking
    hyphens, en dashes and typographic quotes. Printing one raises
    UnicodeEncodeError mid-run and takes the whole suite down — losing the
    results already gathered, which on a rate-limited free tier is minutes of
    quota. Replace rather than raise: an unrenderable character is a cosmetic
    problem and a lost run is not.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def run(labels: list[str] | None = None, *, verbose: bool = False) -> int:
    _make_stdout_safe()
    load_keys()
    client = llm_module.get_llm(refresh=True)
    grade = llm_module.grade_of(client)

    print(f"\nprovider : {client.name}")
    print(f"model    : {getattr(getattr(client, 'provider', None), 'model', '-')}")
    print(f"grade    : {grade.upper()}")
    if grade != "calibration":
        print("           ^ exploratory only. These scores are not student-facing")
        print("             and do not enter the calibration corpus.")
    print()

    if not llm_module.is_available():
        print("no provider configured — put a key in keys.txt (see required_keys.txt)")
        return 2

    questions = get_questions()
    cases = [c for c in regression_cases() if not labels or c.label in labels]

    header = f"{'case':<24} {'band':<7} {'correct':<8} {'depth':<7} {'comm':<6} {'in band':<8}"
    print(header)
    print("-" * len(header))

    passed = failed = errored = 0
    for case in cases:
        package = questions.by_label(case.question_label)
        turn = TurnInput(
            turn_id=uuid.uuid4(),
            candidate_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            question_id=package.question_id,
            answer_text=case.answer_text,
        )
        evaluation = evaluate_turn(turn, llm=client, question=package)

        if not evaluation.aggregated:
            reason = evaluation.evaluators[0].dropped_reason or "no scores"
            print(f"{case.label:<24} {'-':<7} !! {reason[:60]}")
            errored += 1
            continue

        by_key = {s.dimension_key: s.raw_score for s in evaluation.aggregated}
        # The concept-bearing dimension is the one the band is set against —
        # it is what becomes mastery, so it is what the suite judges.
        judged = by_key.get("correctness")
        ok = judged is not None and case.contains(judged)
        passed += ok
        failed += not ok

        band = f"{case.expected_band[0]}-{case.expected_band[1]}"
        print(
            f"{case.label:<24} {band:<7} "
            f"{by_key.get('correctness', '-'):<8} {by_key.get('depth', '-'):<7} "
            f"{by_key.get('communication', '-'):<6} {'yes' if ok else 'NO':<8}"
        )
        if verbose:
            for score in evaluation.aggregated:
                quote = score.evidence[0].span.quote if score.evidence else ""
                print(f"    [{score.dimension_key}] {score.reasoning}")
                print(f'      cited: "{quote[:90]}"')

    total = passed + failed
    print("-" * len(header))
    print(f"{passed}/{total} within band" + (f", {errored} errored" if errored else ""))
    fitness = "calibration-eligible" if grade == "calibration" else "exploratory"
    print(f"(grade={grade} — {fitness})")
    return 0 if failed == 0 and errored == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", nargs="*", help="case labels; default all")
    parser.add_argument("-v", "--verbose", action="store_true", help="show reasoning and citations")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return run(args.labels or None, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())

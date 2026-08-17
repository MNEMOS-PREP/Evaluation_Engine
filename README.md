# M13 — Evaluation Engine

> **The spine.** Everything else in the platform is a producer or a consumer of this module.
>
> Spec: [plan_in_depth/M13_Evaluation_Engine.md](plan_in_depth/M13_Evaluation_Engine.md) (Revision 2) · Review that produced it: [M13_REVIEW.md](plan_in_depth/M13_REVIEW.md) · Ports: API `8113` ([PORTS.txt](PORTS.txt))

Given an answer, produce a score a human rater would agree with, and prove it by quoting the exact words that earned it. That is the whole module, and it is the entire trust proposition of the product: a confidently fabricated "7.5/10" is worse than no score at all, because it teaches students the wrong things and no placement cell will ever rely on it.

```bash
git clone https://github.com/MNEMOS-PREP/Evaluation_Engine
cd Evaluation_Engine/Backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # 83 passed, no network, no API key
cd .. && start_eval.bat                 # API on :8113
```

No API key needed to run the tests or the server. Scoring is the one feature that switches off without one, and `/v1/deps` says so rather than fabricating a number.

---

## What is built

This is milestones **M0–M3** of the [§14 build order](plan_in_depth/M13_Evaluation_Engine.md) — the spine, in highest-risk-first order.

| Milestone | What landed |
|---|---|
| **M0 — Contracts & the seam** | `ai_core.evidence` consumed rather than redefined · `concept_bearing` · typed `AppliesWhen` · published hint-penalty table · `/health` + `/v1/deps` + `module.json` · fixture adapters for M5 and M12 |
| **M1 — Rubrics** | Typed rubric schema, YAML loader, `dsa_verbal` authored with behavioural anchors at every level, disqualifiers as flags |
| **M2 — Blind projection** | `EvaluatorView` and `PairwiseView`, both with the architectural leak test — **AC-13.2** |
| **M3 — One evaluator** | Structured output with enum-constrained scores · span verification, repair and reject/retry · artifact snapshot + checksum · injection neutralisation — **AC-13.16** |

**83 tests, 14 of them release gates, ruff clean, and not one of them opens a socket.**

### What is deliberately not built

`GET /v1/deps` and the spec's §14 are the honest list, but the short version: no ensemble (M4), no NLI coverage or M04 observation emit (M5), no rater workbench (M6), no calibration and therefore **no displayed numbers** (M9), no student UI (M10). Endpoints for those are absent rather than stubbed — an endpoint that exists and returns a placeholder is worse than one that does not, because a caller writes against it and finds out later.

---

## The five things worth reading the code for

**1. The repair path overwrites the quote from the artifact.** [`evidence.py`](Backend/backend_M13_Evaluation_Engine/evidence.py) · Models get offsets slightly wrong while quoting real text, so repair exists. Fix the offsets and keep the *model's* string, though, and a paraphrase ends up in the field the UI captions "What you said" — at a 0.95 ratio, enough to turn *"I think it overwrites"* into *"it overwrites"*. One assignment (`span.quote = artifact[span.start:span.end]`) is the difference, and **AC-13.16** asserts it over the whole table rather than at write time.

**2. Injection is neutralised in place, never stripped.** Strip it and every offset after it shifts, so a genuine later quote either fails to verify or — worse — verifies against the wrong characters and shows a student words that are not theirs. The replacement is padded to equal length, which is the entire trick, and there is a test with an injection *mid-answer* asserting the content after it is still quotable.

**3. The blind projection is enforced by a graph walk, not by the prompt.** [`projection.py`](Backend/backend_M13_Evaluation_Engine/projection.py) · `leaks_identity()` walks a view's type graph and reports every path reaching candidate identity. It is exact, because a graph walk is deterministic — which is why **AC-13.2** can honestly target 100% while the counterfactual bias gate (AC-13.3) has to be statistical. There is a control test proving the walker actually fails on a type that leaks.

**4. `raw_score` is an `enum`, not a range.** [`schemas.py`](Backend/backend_M13_Evaluation_Engine/schemas.py) · Structured outputs **drop** `minimum`/`maximum`, so `{"type":"integer","minimum":0,"maximum":4}` silently accepts a `7`. EC-13.12 calls an out-of-range score a "schema rejection"; `enum` is what makes that true. `artifact_id` is enumerated the same way, so a hallucinated artifact id cannot be returned at all.

**5. The ensemble will need a decorrelator, and the reason is in the model roster.** `claude-sonnet-5` and `claude-opus-5` reject `temperature`, `top_p` and `top_k` with a 400 — they were removed. So two identical calls to one model are one sample twice, `spread` collapses toward zero, and a confidence badge built on it reports determinism as agreement. `dimension_order_seed` is the lever, already plumbed and tested for rubric-neutrality.

---

## Layout

```
Backend/backend_M13_Evaluation_Engine/
  contracts.py    §5 — the shapes four other modules read
  rubrics.py      §6.1 — loader; every rule fails at LOAD, not at scoring time
  rubrics/*.yaml  the anchors. The highest-leverage authoring work here.
  projection.py   §6.2 — EvaluatorView, PairwiseView, and the AC-13.2 walk
  evidence.py     §6.3 — freeze, verify, repair, neutralise
  schemas.py      §6.4 — the structured-output contract
  evaluator.py    §6.3 — one evaluator with reject-and-retry
  service.py      §6.4 — freeze → project → score → credit → compose
  adapters.py     §6.11 — the M5/M12 seam, fixture-backed
  llm.py          §11 — provider, tiers, cost, cache-minimum guard
  fixtures/       the M5 stand-in AND the regression suite seed
```

## Conventions worth knowing before you edit

- **A rubric that breaks a §6.1 rule fails to load.** Missing anchor level, zero or two `concept_bearing` dimensions, hint credit that rises with help, unknown `applies_when` field — all load-time errors with a sentence naming the problem.
- **Bands never come from a model.** Every regression case records a `band_source`, and a gate asserts none of them is model-derived. Snapshotting today's output as the expected band freezes today's bias as tomorrow's ground truth (Trap 9).
- **`model_confidence` is never rendered.** It feeds ECE. What a student sees is `agreement`, and a single-evaluator run is never "high" — one evaluator agreeing with itself is not evidence.
- **No test opens a socket.** `StubLLM` has an explicitly *dishonest* mode, because the evidence gate is only meaningful if something in the suite tries to get past it.

## Before the next milestone

Two items are not engineering and are on the critical path — see [§6.6](plan_in_depth/M13_Evaluation_Engine.md) and [the review](plan_in_depth/M13_REVIEW.md) Part 4:

1. **File the ethics annexe** and open rater recruitment. Clearance gates recruitment, recruitment gates annotation, annotation gates every displayed number in the product. It takes weeks and no code removes it from the path.
2. **Decide the concept-bearing dimension per round type** before more rubrics are authored, and the scaffold-stratification question before annotation starts — both change what gets sampled.

# M13 — Evaluation Engine

> **The spine.** Everything else in the platform is a producer or a consumer of this module.
>
> Spec: [plan_in_depth/M13_Evaluation_Engine.md](plan_in_depth/M13_Evaluation_Engine.md) (Revision 2) · Review that produced it: [M13_REVIEW.md](plan_in_depth/M13_REVIEW.md) · Ports: API `8113`, web `5213` ([PORTS.txt](PORTS.txt))

Given an answer, produce a score a human rater would agree with, and prove it by quoting the exact words that earned it. That is the whole module, and it is the entire trust proposition of the product: a confidently fabricated "7.5/10" is worse than no score at all, because it teaches students the wrong things and no placement cell will ever rely on it.

```bash
git clone https://github.com/MNEMOS-PREP/Evaluation_Engine
cd Evaluation_Engine/Backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # 134 passed, no network, no API key
cd ../Frontend && npm install
cd .. && start_eval.bat                 # API on :8113, web on :5213
```

No API key needed to run the tests or the server. Scoring is the one feature that switches off without one, and `/v1/deps` says so rather than fabricating a number.

---

## What is built

Milestones **M0–M5 and M9** of the [§14 build order](plan_in_depth/M13_Evaluation_Engine.md), plus the API surface for M6 and M10. The module is **complete with respect to its contracts with other modules** — see [CONTRACTS.md](CONTRACTS.md), which is the document to read before wiring a sibling.

| Milestone | What landed |
|---|---|
| **M0 — Contracts & the seam** | `ai_core` evidence and version types consumed, not redefined · `concept_bearing` · typed `AppliesWhen` · published hint-penalty table · `/health` + `/v1/deps` + `module.json` · fixture adapters for M5 and M12 |
| **M1 — Rubrics** | Typed schema, YAML loader, `dsa_verbal` with behavioural anchors at every level, disqualifiers as flags |
| **M2 — Blind projection** | `EvaluatorView` and `PairwiseView`, both with the architectural leak test — **AC-13.2** |
| **M3 — One evaluator** | Enum-constrained structured output · span verification, repair and reject/retry · artifact snapshot + checksum · injection neutralisation — **AC-13.16** |
| **M4 — Ensemble** | N-way independent members with rubric-neutral decorrelation, median aggregation, `spread_levels`, frontier adjudicator. A homogeneous config is **rejected**, not discouraged |
| **M5 — Emit** | Key-point coverage (NLI adapter, lexical fallback) · M04 observations with M04's own uuid5 · M02 coverage ledger · M19 ledger entries · outbox with retract-on-rescore |
| **M9 — Calibration** | Isotonic fit, QWK, Krippendorff α, ECE, length-bias β — and the display gate, with reasons in words a human can read |
| **M10 — The UI** | The evidence drawer, the key-point checklist and the dispute dialog on `:5213` — plus a screen for every endpoint the API serves. See [Frontend/README.md](Frontend/README.md) |

**134 tests, 25 release gates, ruff clean, a clean `tsc`, and not one test opens a socket.**

### What is deliberately not built

No rater workbench that opens an answer, because **AC-13.15** — de-identification before a peer rater sees a transcript — is not built; the queue returns ids, the screen says why, and shipping a form that showed a classmate's name would have satisfied the endpoint while breaking the criterion protecting a real person. Fact-check (FR-13.10) and pairwise/Bradley–Terry (FR-13.11) are P1 and deferred.

And the one that is not an engineering gap: **no calibration is fitted**, so `display_numeric` is false everywhere and `composite` is `None`. The module produces real, evidence-verified judgements today and refuses to show any of them as a number. That is gated on the annotation study — ethics clearance, then ~2,400 human ratings — which no amount of code shortens.

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
  ensemble.py     §6.4 — N members, median, spread, adjudication
  coverage.py     §6.5 — key-point coverage; the method travels with the number
  emit.py         §5  — what M04, M02 and M19 receive. Start here to wire a sibling.
  calibration.py  §6.7 — isotonic, QWK, α, ECE, and the display gate
  store.py        §6.11 — persistence, outbox, supersede-and-retract
  adapters.py     §6.11 — the M5/M12 seam, fixture-backed
  llm.py          §11 — provider, tiers, cost, cache-minimum guard
  fixtures/       the M5 stand-in AND the regression suite seed

Frontend/frontend_M13_Evaluation_Engine/src/
  components/Transcript.tsx   offsets become highlights. The trust proposition, rendered.
  components/Judgement.tsx    the ONLY place that decides a number may be shown
  api.ts                      one hook per endpoint, and no hook without one
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

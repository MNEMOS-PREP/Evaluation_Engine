# M13 — Plan Review, Before Implementation

> Reviewed: 2026-08-17 · Target: [M13_Evaluation_Engine.md](M13_Evaluation_Engine.md) · Reviewed against the master plan (§39, §47, §48), the revised [M04](M04_Skill_Graph_Memory.md) (Revision 2), M05, M06, M12, M17, M18, M19, and M15's shipped code and conventions.
>
> **Status of evidence.** Everything in Part 1 and Part 2 I checked by hand — by grep across `plan_in_depth/`, by reading the sibling spec, or by executing the arithmetic; those checks are shown inline. The model-API claims (sampling parameters, structured-output schema limits, prompt-cache minimums, pricing) were verified against the `claude-api` reference rather than from memory. Items marked *(judgment)* are a single reading and worth a second opinion before you act on them.

---

## Verdict

M13 is the best-argued document in the set on the thing that matters most: it treats *evidence* as an architectural constraint rather than a feature, and it is willing to show no number at all. §2.4, §3.1's eight traps, and §6.3's reject-and-retry are the spine of the whole platform's credibility. Do not water any of them down.

The problem is the same one M04 had, one layer up: **M13 is written as the module that produces a score, when its actual job is to be the module that produces an `Observation`, an `EvidenceRef`, a ledger row, and a re-test request** — four typed artifacts that four other modules consume. None of those four contracts appears in the document. §6.4's pipeline ends at "LEDGER WRITE" and the ledger belongs to M19, which is Phase 2–4.

Underneath that, five things are wrong rather than missing:

1. The evidence-repair path can store the model's paraphrase in the field the UI renders as "your actual words" (§2.1). That is the one bug in this module that would be fatal rather than embarrassing.
2. The injection-stripping edge case (EC-13.3) and the span-verification requirement (FR-13.4) contradict each other (§2.2).
3. The pairwise path (§6.5) feeds the candidate's own prior answer to the evaluator, which the blind projection (§6.2) forbids and AC-13.2's architectural test would fail on (§2.3).
4. The ensemble is not independent on the models this project actually runs (§2.6) — `spread` will be systematically near zero and the confidence badge will be decorative.
5. The cost table in §11 is off by roughly **75×** — it is the master plan's *dollar* figures with a rupee symbol (§6.1). Verified by arithmetic against §47.2 and M06 §11.

None of it is deep. It is about **three days of contract work, one day of pipeline corrections, and an honest re-estimate** of a 14-day plan that is really ~19 — plus the one calendar dependency nobody has started: ethics clearance, which gates the calibration study that gates every number in the product.

---

## Part 1 — Settle these before writing a line of M13

Six contracts. Everything downstream inherits them, and each is cheap now and a migration later.

### 1.1 `EvidenceSpan` is no longer M13's type — consume it, don't define it

**Verified.** M04 Revision 2 §5.1 moves `EvidenceSpan` into `ai_core.evidence` (Platform_Core v0.2.0) and adds `EvidenceRef` around it, with the note *"M13 produces them, M04 stores them, M19's ledger projects over them, M16 renders them."* M13 §5 still declares its own `EvidenceSpan`, and the two have already drifted: M04's has `artifact_type` including `"submission"` and defaults on `t_ms`/`verified`; M13's does not.

Two copies of the type that carries "every number traces to evidence" is exactly the failure `dependencies.txt` argues against for `SourceChip`. Delete M13's declaration, import the platform one, and add the wrapper M04 requires:

```python
from ai_core.evidence import EvidenceSpan, EvidenceRef     # Platform_Core v0.2.0
```

Then change `DimensionScore.evidence` to `list[EvidenceRef] = Field(min_length=1)` — FR-13.3 currently lives in prose and a non-empty list is what actually enforces it.

**The `checksum` field is not decoration.** `EvidenceRef.checksum` is `sha256(artifact)` at write time, and M04's resolution rule is *artifact exists AND sha matches AND `artifact[start:end] == quote`*. M13 is the module that computes it. See §2.15 for why the artifact must be frozen before the ensemble runs.

### 1.2 The M13 → M04 observation contract does not exist

**Verified.** §6.4's step 7 is `LEDGER WRITE`, and §7 has no endpoint that emits anything to M04. Meanwhile M04 §6.2 says *"M13 emits several observations per turn. `POST /observations` takes a **list**, in one transaction"*, and M04's `Observation` requires nine fields M13 never produces:

| M04 requires | M13 has | Gap |
|---|---|---|
| `raw_category: int` (0..K, un-normalised) | `raw_score: int` | rename/alias only — fine |
| `n_categories: int` | — | always 5 for a 0–4 rubric; publish it |
| `response_model: "2pl"\|"grm"\|"3pl"\|"none"` | — | M13 must say which; rubric-scored ⇒ `grm` |
| `item: ItemParams \| None` | — | copied from M05's package **as administered** |
| `source_dimension_key: str` | — | **the concept-bearing dimension — see below** |
| `concept_weight: float` | — | mirrors M05's `ConceptWeight` |
| `weight: float ∈ (0,1]` | — | hint penalty lands here — see §1.4 |
| `consent_id: UUID` | — | see §1.5 |
| `versions: VersionStamp` | four loose strings | see §1.3 |

**The one that matters is `source_dimension_key`.** M04's review §2.6 called this *"arguably the most important unwritten function on the platform"* and M04 Revision 2 wrote the rule: **one observation per `(turn, concept)`, from the single rubric dimension nominated as concept-bearing for that round type; `communication`/`delivery` dimensions map only to `domain='communication'` concepts and never to technical ones.** M13 owns rubrics, so the nomination is a *field on the rubric*, and it does not exist:

```python
class RubricDimension(BaseModel):
    ...
    concept_bearing: bool = False   # exactly one per rubric; feeds M04's theta
```

Add a schema validator asserting exactly one `concept_bearing` dimension per rubric, and a unit test that a rubric with two fails to load. Without it, whoever writes the M04 call will average the dimensions, and communication quality will silently become part of DSA mastery.

Add to §6.4 as step 8, and to §7 as the emit:

```
[8] OBSERVATION EMIT  → POST {M04}/v1/observations   (batch, one transaction)
    one observation per (turn, concept) from the concept-bearing dimension
    + one per communication concept from the communication dimension
    idempotency: uuid5(OBS_NAMESPACE, f"{turn_id}|{concept_id}|{kind}|{rubric_version}")
```

M04 publishes `OBS_NAMESPACE` in its spec precisely so every caller derives the same id; use it rather than inventing one, or the retry path double-counts.

### 1.3 Use M19's `VersionStamp`, don't invent a subset

**Verified.** §6.8 says every score row stamps `{rubric_version, prompt_version, model_id, calibration_version, item_bank_version}` — five strings. M19 §5 already defines `VersionStamp` with exactly those **plus `extractor_versions` and `code_sha`**, and M04 §5.2 stores it verbatim on every observation. `TurnEvaluation` currently carries `rubric_version` and `calibration_version` as bare fields and scatters `model_id`/`prompt_version` onto `EvaluatorOutput`.

Two consequences: a re-score cannot be attributed to a code change (no `code_sha`), and M04's write path receives a shape it has to reassemble. Replace with `versions: VersionStamp` at the `TurnEvaluation` level, and keep the per-evaluator `model_id`/`prompt_version` as *additional* detail inside `EvaluatorOutput` — an ensemble legitimately spans two model ids, and `VersionStamp.model_id` should name the ensemble config, not one member. Add `ensemble_config: str` (see §2.8).

### 1.4 The hint penalty is M13's to publish, and nobody has written it down

**Verified.** `grep -cin "hint" M13_Evaluation_Engine.md` → **0**. Meanwhile:

- Master plan §32.5: *"Hint level used is recorded and reduces the credited score by a published, fixed amount per level (transparent, not secret)."*
- M04 §6.3: *"Hint-assisted correct answers scale `raw_category` by the published hint penalty and take `weight × 0.7`; the penalty is applied **once**, in M13, and M04 does not re-apply it."*
- M06 §5 carries `hint_level_used: int` on the turn; M05's `Question` carries `hint_ladder: list[str]`.

So three modules route to a number M13 does not define. Publish the table in §6.1 next to the anchors, because it is a rubric-level policy, not an implementation detail:

```
hint_level_used  0    1     2     3     4     5
credited factor  1.0  0.95  0.85  0.70  0.50  0.30
```

Two rules with it. **The penalty applies to the credited score, never to the raw score** — `raw_score` stays what the evaluator produced so the calibration and the regression suite stay comparable across hinted and unhinted answers. And the report says so out loud (*"4/4 on the mechanism, credited 3 because you took two hints"*), because master plan §32.5's word is "transparent". The numbers above are a proposal; what is not optional is that *one* table exists and it lives here.

The **coachability** signal §32.5 asks for (*"how much lift does one hint give this candidate?"*) falls out of the same field and is a genuinely good report line — it belongs in M13's output as `hint_lift: float | None`, not re-derived downstream.

### 1.5 Consent, purpose and retention — zero mentions, and raters hear real students

**Verified.** `grep -cin "consent|IRB|DPDP|anonym|retention"` over M13 → **0 for all**; `ethic` appears once, inside open decision §15.2.

This is more exposed than M04's version of the same gap, for one specific reason: **§8.2's rater workbench plays a real student's audio to a peer rater.** The proposal in §15.2 is *"(c) both — peers scale, faculty anchor"*, and a final-year peer rating a classmate's recorded answer is a re-identification surface, not a hypothetical one. Master plan §48.3 already specifies voice de-identification (*"pitch/formant transformation preserving the measured features"*) — for *release*. It is needed earlier, for *annotation*.

Three things, all cheap now:

1. **`HumanRating` and every stored artifact carry `consent_id` and `purpose ∈ {practice, institutional_reporting, research}`.** The calibration study is `research`; revocation then becomes `WHERE purpose='research'` rather than a total wipe. This mirrors M04 §5.4 exactly — one column, same semantics.
2. **The rater workbench serves de-identified audio by default** — voice transformation applied at fixture-build time, name/roll-number scrubbing on the transcript, and a `rater_can_see_identity: bool` that is `False` for peer raters and may be `True` only for faculty adjudication with a logged reason. Add it as **AC-13.15 [GATE]**: no peer rater's workbench request returns un-transformed audio.
3. **The ethics annexe is on the critical path and it is not in the build order.** It needs: what a rater sees, what is stored, the retention class per artifact, the de-identification method, and the D1 (`IIB-Bench`) release plan from master plan §48.1. Half a day to write, weeks to approve. §15.2 says "ethics clearance in Month 1" — make that a build-order milestone on day 1, not an open decision, because **annotation cannot start without it and annotation is the long pole M13 itself names** (§3.2.1).

Retention, stated in §5: evaluations and evidence spans → enrolment + 1 year. `HumanRating` → enrolment + 1 year. Released dataset subset → per its own datasheet.

### 1.6 Say who owns `key_points` — and fix the master plan reference

**Verified.** Master plan §39.1 puts `key_points: list[KeyPoint]` on `Rubric`. M05 §5 puts them on `Question` (*"an item without those is not usable for scoring"*). M13 §5's `Rubric` has neither — and §6.2's `EvaluatorView` reads `turn.question.key_points`, i.e. M13 has already silently chosen M05's placement.

M13 is right and the master plan is wrong: key points are item-specific ("mentions the test set was held out"), rubrics are round-level and reused across hundreds of items. Say so in §6.1 in one line, and amend master plan §39.1 to drop `key_points` from `Rubric`. Leaving both is how M05 and M13 end up with two key-point tables. M01 §456 also hands `expects: list[str]` to M13 as key points — that flows through M05's `Question`, not directly, and the spec should say so.

---

## Part 2 — Corrections inside the pipeline

### 2.1 The evidence repair path can store a paraphrase in the field labelled "your actual words"

**Verified by reading §6.3 against §2.2.** The repair branch:

```python
idx = fuzzy_locate(artifact, span.quote, min_ratio=0.95)
if idx is not None:
    span.start, span.end = idx
    return True
```

It fixes the offsets and **leaves `span.quote` as the model produced it**. `quote` is the field §2.2's mock renders inside the box captioned *"What you said:"*, and §6.3's own closing line is *"Never store an unverified span. The whole product's credibility rests on 'these are your actual words'."* At `min_ratio=0.95` a 60-character quote passes with three characters different — enough to turn *"I think it overwrites"* into *"it overwrites"*, or to normalise a hesitation away.

This is the one bug in M13 that is fatal rather than embarrassing, because it fails *in the direction of looking correct*. One line fixes it:

```python
idx = fuzzy_locate(artifact, span.quote, min_ratio=0.95)
if idx is not None:
    span.start, span.end = idx
    span.quote = artifact[span.start:span.end]   # the artifact is the truth, not the model
    span.repaired = True                          # audit trail; surfaced in the trace, not the UI
    return True
```

Add `repaired: bool` to the span and **AC-13.16 [GATE]**: for every stored span, `artifact[start:end] == quote` after whitespace normalisation — asserted over the whole table in CI, not just at write time. That gate is testable, cheap, and is the actual statement of FR-13.4. Track the repair rate per prompt version; a rising rate means the prompt's offset instructions are drifting.

### 2.2 EC-13.3 and FR-13.4 contradict each other

**Verified.** EC-13.3: *"Answer contains prompt injection → Stripped before evaluation; scored on the remainder."* FR-13.4: *"Mechanically verify every span against the source artifact."*

If the evaluator sees a stripped string, every offset it returns indexes the *stripped* text, and verification against the stored artifact fails — or, worse, succeeds against the wrong characters and points the student's evidence drawer at someone else's words. The evidence drawer would also render a quote that does not exist in the transcript the student can see.

Never mutate the artifact. Instead:

```
1. Detect injection spans on the artifact; store them as `neutralised_spans` on the turn.
2. The EvaluatorView presents the artifact WITH those ranges replaced by a fixed
   marker of equal length — "[removed]" padded — so offsets are preserved exactly.
3. Reject any returned span that overlaps a neutralised range.
4. Log the attempt. Score the remainder. Never mention it to the student mid-session.
```

Equal-length substitution is the trick that keeps FR-13.4 mechanical. Add a unit test with an injection in the middle of an answer asserting that a span *after* the injection still verifies.

### 2.3 The pairwise path violates the blind projection, and AC-13.2 would catch it

**Verified.** §6.2's `EvaluatorView` lists as DELIBERATELY ABSENT: *"prior scores … other turns, session metadata"*. §6.5 step 1: *"Sample comparators: 2 reference answers at known quality levels **+ the candidate's own best prior answer on a similar item**."*

That is another turn by the same candidate, entering the evaluator's context. AC-13.2 is *"Evaluator projection cannot reach candidate identity — architectural test"*, and a type-graph walk over a view that contains a prior `Turn` reaches `Candidate` in one hop. So the module's own P0 gate fails on its own P1 feature, and the failure surfaces on day 12, not day 2.

Master plan §39.4 does want this (*"the candidate's own past answers … the 'you vs you 3 months ago' readout falls straight out of this"*), so the answer is a carve-out, not a deletion. Write it explicitly in §6.5:

> **Comparators are anonymised at projection time.** A comparator enters `PairwiseView` as `ComparatorText{text, quality_band}` — a bare string and a band, with no turn id, no candidate id, no timestamp, no route back. Provenance (own-prior vs reference) is held by the *caller* and never crosses the boundary. Presentation order is randomised and counterbalanced, so A/B position carries no signal either. The architectural test asserts `PairwiseView`'s type graph reaches neither `Candidate` nor `Turn` — it is a second gate, not an exemption from the first.

### 2.4 §6.5's per-candidate Elo is a second persisted ability estimate

**Verified against M04 Revision 2 §6.3**, which settled exactly this class of bug for θ: *"M04 owns the durable posterior … the only thing persisted, the only thing displayed."* §6.5 step 5 says *"Online: maintain an Elo per candidate per dimension."*

An Elo per candidate per dimension, persisted by M13, is a competing belief about the same latent quantity M04 owns, with no arbitration rule — the identical two-source-of-truth bug across a repo boundary, which M04's review calls "the hardest kind to find". Two months in, the communication bar on the report and the communication mastery on the map disagree and nobody can say which is right.

Fix: **the Bradley–Terry latent `θ_q` is a per-item scoring artifact, not a per-candidate ability.** M13 fits BT over the comparison graph, maps to 0–4 via the reference anchors (steps 3–4 as written), and stops. The candidate-level aggregation is an `Observation` on a `domain='communication'` concept, written through `record()` like everything else. Delete step 5.

### 2.5 EC-13.10 needs a signal §6.2 forbids

**Verified.** §6.2 excludes `probe_intent`. EC-13.10: *"Steelman turn (interviewer said something false) → Rubric switches to `push_back` dimension."* M06 §6.5 stores the turn with `deliberately_false=True`.

The evaluator cannot switch rubrics on information it is not given. Resolve it at the caller, where it costs nothing: **the rubric is selected before projection.** M06 passes `rubric_id` with the evaluation request; a `deliberately_false` turn is dispatched against the `push_back` rubric variant. The evaluator still sees only question + reference + rubric + answer, and the rubric it sees happens to be the one whose dimensions are about disagreement. Nothing leaks, because "which rubric am I applying" is not "what was the interviewer thinking".

Say that in §6.2 as a general rule — *rubric selection is the caller's; the evaluator never learns why* — because the same pattern will recur for every turn-kind-conditional behaviour.

### 2.6 The ensemble is not independent on the models this project runs

**Verified against the model API reference.** Master plan §47.1 assigns mid tier = `claude-sonnet-5`, frontier = `claude-opus-5`. On both, `temperature`, `top_p`, and `top_k` are **removed and return a 400** — the project's own `IMPLEMENTATION_PLAN.md` §0.3/B.2 already recorded this for M15.

§6.4's default is *"2× mid tier + 1× frontier"*. The two mid-tier calls are the same model, same prompt, same schema, with no sampling knob to vary. They will agree far more often than two independent raters would, which means:

- `spread` is systematically compressed toward 0,
- adjudication fires far below the 15% §11 budgets for,
- the confidence badge in §2.2 (*"3 of 3 evaluations agreed"*) reports near-agreement as high confidence when it is mostly determinism,
- and Trap 5's own warning (*"calling the same model 3× is not an ensemble"*) is violated by the default configuration, one section later.

Three fixes, cheapest first, and you want at least the first two:

1. **Make heterogeneity mandatory, not budget-permitting.** `N=3` becomes 1× frontier + 1× mid + 1× mid-with-a-decorrelating-perturbation, and the composition is a named `ensemble_config` value, not an implicit default.
2. **Decorrelate the two mid-tier calls by something rubric-neutral**: present the dimensions in a different order, and the key-point scaffold in a different order. Both are order permutations of the *same* content, so neither changes what is being asked; both break byte-identical prompts. Add a regression test asserting the permutation does not change the mean score by more than 0.1 levels (if it does, the rubric is order-sensitive, which is its own bug worth finding).
3. **Measure it.** Report observed `spread` distribution per `ensemble_config` in the first agreement study. If homogeneous pairs agree 98% of the time, the third call is buying nothing and §15.1's open decision answers itself with data.

Note the interaction with prompt caching: permuting the dimension order changes the cached prefix, so cache the *stable* half (rubric preamble, instructions, output schema) and put the permuted block after the last breakpoint. Which leads to §6.2 below.

### 2.7 `spread` is two different quantities in the same document

**Verified.** §5: `spread: dict[str, float]  # per-dimension σ`. §6.4 step 4: `spread = max - min`. §6.4 step 5 and §10 both threshold on `≥ 2`. Master plan §39.3: *"σ computed … if σ > τ (default 1 level)"*.

Three statements, two quantities, two thresholds. With N=3 on a 0–4 scale, `max−min` and σ are not interchangeable: scores {2,2,4} give range 2 and σ ≈ 0.94, so a σ>1 rule and a range≥2 rule disagree on a case that will be common.

Pick range — it is interpretable to a rater ("two levels apart"), robust at N=3, and it is what the adjudication prose actually means. Then say so in one place: rename to `spread_levels: dict[str, int]`, define it as `max − min`, threshold at `≥ 2`, and amend master plan §39.3's σ language to match. Keep σ if you want it for the paper, under a different name.

### 2.8 A calibration fitted on N=3 medians is applied to N=1 outputs

**Verified by reading §6.4's cost-control note against §6.6 and §6.7.** §6.4: *"In degraded modes (M6 §26.6) N drops to 2 then 1."* Master plan §47.2 makes this routine, not exceptional: *"Practice mode (N=1 evaluator, deferred re-score)."* §6.6 fits `CalibrationModel` on the calibration corpus, which is scored with the full ensemble.

A median of three is a different estimator from a single draw — lower variance, different bias. Applying a Platt/isotonic map fitted on the first to the second is out-of-distribution use of a calibration, and it is invisible: the student sees a number that looks identical to a fully-scored one. This is the same class of error as Trap 7 (comparing across rubric versions) with the ensemble as the moving part instead of the rubric.

`CalibrationModel` needs `ensemble_config: str` in its key, and the display gate needs one more clause:

```
display_numeric = ... AND (calibration.ensemble_config == evaluation.ensemble_config)
```

Then two honest options per config, and you should ship both: fit a separate (cheap) calibration for `n1_practice` from the same corpus by subsampling one evaluator per item — free, since the per-evaluator outputs are already stored — or suppress the number in degraded runs and backfill it when the overnight batch re-score lands, which §6.4 already schedules. The second is the better default for Practice mode, because the student is told the re-score is coming and the report gains a number rather than silently changing one.

### 2.9 `calibration_status` on the rubric makes calibration a rubric change

**Verified.** §5 puts `calibration_status` and `display_numeric` on `RubricDimension`. §6.7 says the gate *"is checked at render time from `CalibrationModel`, not hardcoded, so a dimension can go live the moment its numbers clear."* Those two sentences describe different systems.

Worse, `RubricDimension` lives inside a **versioned** `Rubric`, and §6.8 says a rubric bump *"enqueues `rescore_job` over affected turns"*. So flipping a dimension from `calibrating` to `calibrated` — a fact about a fitted model, not about the rubric — would bump the rubric version and trigger a batch re-score of the entire history. It also makes every historical score incomparable across a change that changed nothing about how answers are judged.

Delete both fields from `RubricDimension`. They are properties of `CalibrationModel[(dimension_key, round_type, ensemble_config)]`, resolved at render time, exactly as §6.7 already says.

### 2.10 "Confidence" means two things and ECE measures one of them

**Verified.** `DimensionScore.confidence: float` is produced by each evaluator (model self-report). §2.2's UI renders *"Confidence: high (3 of 3 evaluations agreed)"* — ensemble agreement. AC-13.9 targets `ECE ≤ 0.10` without saying which.

They measure different things and should not share a word. Split:

- `model_confidence: float` — per evaluator, self-reported. **This is what ECE and Brier are computed on** (AC-13.9), because calibration of self-reported confidence is the published claim.
- `agreement: Literal["high","medium","low"]` — derived from `spread_levels` and whether adjudication fired. **This is what the badge shows**, because it is the thing a student can act on.

The report never shows `model_confidence` to a student. A model's opinion of its own reliability is a research instrument, not a user-facing fact.

### 2.11 The NLI scaffold makes the "model-independent" coverage measure not independent

**Verified by reading §6.4 step 1 against §10.** Step 1's stated purpose is *"gives the evaluator a factual scaffold **and** gives us a model-independent coverage measure"*. Those two purposes conflict: once the coverage vector is in the evaluator's context, the evaluator's score is conditioned on it, and `key_point_coverage` is no longer an independent measurement of the same answer — it is an input to the thing it is being compared against.

And §10's fallback (*"NLI service down → skip coverage scaffold; evaluators still run"*) silently changes the measurement mid-corpus: some evaluations saw the scaffold and some did not, with nothing on the row saying which. That contaminates the calibration corpus in a way that is very hard to detect later.

Two lines fix it. Store `scaffold_used: bool` on `TurnEvaluation` and **stratify the calibration fit on it** (or exclude scaffold-less runs from the fit). And state the honest version of the claim: coverage is *model-independent of the evaluator's judgment* only in the ablation arm. If you want the clean measure, run the NLI pass on a held-out slice with the scaffold withheld — that is a one-line experiment and a better sentence in the paper.

Also unstated: the entailment threshold that turns `key_point_coverage[kp]` into membership of `missing_key_points`. §2.2's checklist renders ✓/✗ per key point, so a threshold exists; publish it (0.5 is a reasonable start), version it, and put it in `VersionStamp`'s orbit — it moves scores.

### 2.12 `applies_when: str` is an unspecified expression language

**Verified.** `applies_when: str | None  # "modality == 'coding'"`. Nothing says who evaluates it. The default implementation is `eval()` on a string from a YAML file, which is a code-execution path in the module that everything else trusts.

It does not need to be general. Two comparisons cover every example in the spec set:

```python
class AppliesWhen(BaseModel):
    field: Literal["modality","round_type","turn_kind"]
    op: Literal["eq","in"]
    value: str | list[str]
```

Typed, testable, no evaluator, and a rubric with an unknown `field` fails to load instead of failing at scoring time.

### 2.13 EC-13.12 does not work as written — structured outputs cannot express `0..4`

**Verified against the structured-outputs schema limits.** EC-13.12: *"Model outputs a score outside 0–4 → schema rejection → retry → drop that evaluator."* But JSON-Schema **numeric constraints (`minimum`, `maximum`, `multipleOf`) are not supported** by structured outputs — a schema declaring `{"type": "integer", "minimum": 0, "maximum": 4}` has the constraint stripped, and a `7` comes back cleanly typed and out of range.

`enum` **is** supported. Use it:

```json
"raw_score": {"type": "integer", "enum": [0, 1, 2, 3, 4]}
```

Now the constraint is structural and EC-13.12's "schema rejection" is real rather than aspirational. Two related notes for the same schema: `additionalProperties: false` and `required` on every field (M15's B.4 already proved this pattern out for grounding IDs), and `anchors: dict[int, str]` serialises to string keys in JSON — `{"0": ...}` — so the loader must coerce, or the anchor-completeness unit test will pass in Python and fail against a stored rubric.

The stronger version of the same idea, worth taking from M15's shipped work: **enumerate the legal evidence surface in the schema**. If the answer is chunked, `artifact_id` can be an `enum` of this turn's artifacts, which makes a hallucinated artifact id structurally impossible rather than caught downstream.

### 2.14 Evidence spans have one `t_ms` and no stated source of word timings

**Verified.** `EvidenceSpan.t_ms: int | None  # for audio playback`. §2.2's mock renders a play button per quote, which needs a start *and* an end, and §8.1 requires *"quotes with audio playback"*.

Where do the timings come from? M11 §6 produces word-level alignment (WhisperX), and M17 §6 builds a fused timeline on word timings. M13 never names the dependency. Say it: **character offsets are the contract; `t_ms` is derived by mapping `[start, end)` through M11's word alignment, and is `None` in text mode.** Add `t_end_ms`. And add an edge case that will otherwise bite in Phase 3: if alignment is re-run, offsets stay valid but timings change — which is fine, because `t_ms` is derived on read rather than stored as truth. Store the alignment version.

### 2.15 The artifact must be frozen before the ensemble runs

*(judgment, but it follows from §1.1.)* Evidence spans are offsets into a mutable thing. An ASR correction, a late-arriving diarisation pass, or a student editing a code buffer after submission all shift offsets and silently invalidate every stored span — and `EvidenceRef.checksum` is exactly the mechanism M04 built to detect it, which means M13 must be the one to compute it.

State in §6.4, before step 1: *the artifact set is snapshotted and hashed at evaluation time; `EvidenceRef.checksum` records it; a re-score re-snapshots and gets a new checksum.* A span whose checksum no longer resolves is tombstoned, which is what M04 §5.1's resolution rule already assumes.

### 2.16 Nobody owns the composite, and §2.4 promises one

**Verified.** `RubricDimension.weight: float` exists, so a weighted composite is intended. §2.4 mentions *"a single 'readiness' word"*, §15.3 asks whether to show a composite at all, and §8.1 says delivery must *"never [be] averaged together into one headline number without the breakdown visible"*. No formula, no owner, no rule for what happens when one dimension is display-suppressed.

M19 renders the report and M16 consumes trajectories, so both will invent one if M13 does not. Write it in §6.4:

```
composite = Σ(w_d · calibrated_d) / Σ(w_d)   over dimensions where display_numeric
composite is None if ANY contributing dimension has display_numeric == False
```

The `None` rule is the important half and it is the same discipline as §2.4: a composite computed over the subset that happens to be calibrated is a different measurement each week. Delivery dimensions are excluded from the content composite by construction (M12's channels are a separate section per §8.1 and M19 FR-19.7) — say that in the formula, not only in the UI rules.

### 2.17 `disqualifiers` is a list of strings with no mechanism

**Verified.** `Rubric.disqualifiers: list[str]  # "fabricated a library that does not exist"`. §15.5 decides the *policy* (penalise heavily, flag prominently, never auto-zero) but nothing says how one is detected, which dimension it lands on, or what the student sees.

Given §15.5's decision — which is right — the honest implementation is that a disqualifier is **a flag, not a score modifier**: the evaluator returns `disqualifiers_triggered: list[str]` with an evidence span each (same verification path as any other span, so an unverifiable one is dropped), it renders as a prominent note rather than arithmetic, and it feeds M18's memorisation/fabrication probes. Then §15.5's "never auto-zero" is enforced by the *type* — there is no field through which a disqualifier could zero anything.

---

## Part 3 — Cross-module contracts

### 3.1 M13 has no `/health`, no `/v1/deps`, and no story for running alone

**Verified.** `grep -cin "health|/v1/deps|module.json|degrad"` over M13 → 0, 0, 0, 1 (and the one `degrad` hit is about degraded ensemble modes, not module degradation).

Every other module in this repo set clones and runs alone — `README.md`'s first promise, and the thing M15 actually shipped. M13's upstreams are **M05 (question packages, rubric bindings, key points) and M12 (delivery)**, and neither exists. M12 is Phase 3; M13 is Phase 1. As written, day 3 of M13's build order requires a `Question` from a module that will not exist for months.

Add, on day 1, the same three things M15 has and M04 Revision 2 adopted:

```
GET  /health        → {"status", "rubric_set_version", "calibration_version"}
GET  /v1/deps       → which upstreams are up, and what breaks without them
module.json         → M05 (required: false), M12 (required: false), M04 (required: false)
```

And the seam that makes it true: **question packages and delivery vectors enter through an adapter with a fixture implementation.** M13's own regression suite (§12) is 200 frozen `(question, answer, expected band)` cases — that *is* the fixture set. Point the adapter at it and M13 develops, demos and tests standalone with no sibling running, which is also what makes the adversarial suite runnable in CI.

Degradation behaviour, stated per upstream:

| Missing | Behaviour |
|---|---|
| M05 | Fixture/bank adapter; grounded items unavailable; `item = None` so the observation is not θ-eligible |
| M12 | Delivery section omitted with an explicit note (EC-13.14 already covers this) |
| M04 | Observations queued to an outbox and replayed; scoring and the report are unaffected |

That last row matters: M13 must not fail a student's evaluation because a downstream module is down. The outbox is the same pattern M04 §6.2 uses for its own events.

### 3.2 `delivery: dict[str, float]` drops the field that makes M12's P0 gate work

**Verified.** `TurnEvaluation.delivery: dict[str, float] | None  # from M12, kept SEPARATE`. M12's actual contract is `FusedAssessment` — `delivery_subscores`, `channel_contributions`, `confidence`, `suppressed_channels`, `suppression_reasons` — and every underlying signal carries a `disposition ∈ {scored, coaching, diagnostic, suppressed}` (M12 §5) with FR-12.10 as a P0 gate: *"No signal reaches `scored` without a completed validity record."*

Flattening to `dict[str, float]` at M13's boundary erases `disposition` and `suppressed_channels`. Once erased, M13 cannot tell a scored sub-score from a coaching-only observation, and M12's gate — the one thing that makes the facial-analysis work defensible rather than a liability — stops being enforceable one module downstream. It also loses the suppression *reasons* that M12 §6.5 turns into genuinely helpful UI (*"couldn't measure — your camera was backlit"*).

Store `delivery: FusedAssessment | None` and import the type. If the coupling is unwelcome in Phase 1, the minimum is `{subscores, suppressed_channels, suppression_reasons, dispositions}` — but the typed import is less work than the subset.

Add **AC-13.17 [GATE]**, the mirror of M12's own: no delivery signal with `disposition != "scored"` contributes to any numeric M13 emits.

### 3.3 The dispute promise has no plumbing

**Verified.** §2.3 promises *"a human will look at this within 2 days, and I've scheduled a fresh question on this topic for your next session either way."* §7 has `POST /v1/evaluations/{id}/dispute` and nothing else — no review queue, no resolution endpoint, no owner, no SLA mechanism, and no way to schedule the re-test.

The re-test half is already solved and M13 just has to call it. M04 Revision 2 §6.9 owns `m04_retest_queue`, with `requested_by ∈ {'M04','M13','M16'}` and `bypass_freshness: bool = True` — the flag exists *because* M05 never repeats an item within 90 days, so without it the promise is empty. Wire it:

```
POST /v1/evaluations/{id}/dispute
  → dispute row (open)
  → POST {M04}/v1/retest-queue  {reason: "dispute", requested_by: "M13",
                                 concept_id, source_ref: dispute_id,
                                 bypass_freshness: true, expires_at: +60d}
  → student sees: "We've queued a recursion question for your next session."
```

Then the human half, which §7 is missing entirely:

```
GET  /v1/disputes/queue           ?status=open   (internal, oldest first)
POST /v1/disputes/{id}/resolve    {upheld: bool, note, corrected_scores?}
```

An upheld dispute is an **append**, never an overwrite (EC-13.13 already says so), and it must also **retract the observation** — see §3.4. Name an owner and a rota for the 2-day SLA in §15, because a promise on screen with nobody on the other end is worse than no promise.

### 3.4 A re-score must retract, not compensate

**Verified.** §6.8: *"A rubric bump enqueues `rescore_job` over affected turns … Both scores retained."* Retaining both is right for the ledger. But M04 has already consumed the first score as an `Observation` and folded it into a posterior — so a re-score that only appends leaves θ carrying both the old and the new evidence for the same turn, double-counting it.

M04 Revision 2 §6.2 built the mechanism and names M13 as a caller: *"`retracted_at` is set; mastery for that `(candidate, concept)` is **recomputed from surviving observations**, never compensated by an inverse update. M5 EC-5.9, **M13 re-scores**, EC-4.7 disputes and EC-4.10 account merges all route here."*

So the re-score path is: append the new evaluation → retract the superseded observation → emit the new one. Three calls, one transaction on M04's side. Say it in §6.8, and add it to EC-13.13 (upheld dispute) which has the same shape.

### 3.5 Smaller contract gaps, one line each

- **M02's coverage ledger.** M02 §345: *"When M13 scores that turn, the row moves to `scored` with the score. … This is the mechanism that makes coverage a guarantee rather than an intention."* M13 never mentions it. One more emit alongside the observation.
- **M18's separation rule needs a reciprocal test.** M18 §394: *"there is no field on `TurnEvaluation` or `Mastery` sourced from an integrity signal. A CI dependency check enforces this."* M13 owns `TurnEvaluation`, so the test belongs in M13's suite too — a one-way check that lives only in M18 passes forever if M13 adds the field.
- **M17 reads `TurnEvaluation` directly** (§6: `build_timeline(turn, delivery, eval)`) and maps NLI coverage back to word timings. That makes `key_point_coverage` and the entailment threshold (§2.11) part of a public contract, not an internal.
- **M14 scores GD turns through M13's rubrics** with evidence spans pointing at *contribution IDs* (§435). `EvidenceSpan.artifact_type` has no member for that — `"contribution"` needs adding to the platform enum, which is a Platform_Core change and therefore a coordinated one. Phase 3, but decide the name now.
- **The re-score job needs a status surface.** §7's `POST /v1/rubrics` "triggers rescore planning" with no `GET` to see whether it ran. Add `GET /v1/rescore-jobs`.

---

## Part 4 — Measurement, and the study everything depends on

### 4.1 `HumanRating` cannot feed the MFRM it is collected for

**Verified.** §5:

```python
class HumanRating(BaseModel):
    item_id: UUID     # the turn being rated
    rater_id: str
    dimension_key: str
    score: int
    ...
```

§6.6 specifies *"MFRM (facets: candidate ability × item difficulty × rater severity)"*. Three facets, and the table carries **one** of them (`rater_id`). `item_id` is documented as the *turn*, which conflates the psychometric item (the question) with the response, so item difficulty cannot be separated from candidate ability — the two facets collapse into whichever the turn happens to encode.

MFRM is what §6.6 itself calls the thing that *"makes Paper 1 credible to an educational-measurement reviewer"*, and as specced the data cannot be fitted. Add:

```python
turn_id: UUID              # the response (renamed from item_id — it is not the item)
question_id: UUID          # the ITEM facet
candidate_id: UUID         # the PERSON facet (pseudonymised for the rater — §1.5)
rubric_version: str        # ratings are not comparable across rubric versions either
round_type: str            # calibration is fitted per (dimension, round_type)
consent_id: UUID           # §1.5
purpose: Literal[...]      # §1.5
confidence: int | None     # rater's own certainty; cheap, and it improves adjudication triage
```

Without `rubric_version`, Trap 7 applies to the human ratings exactly as it applies to model scores, and the calibration corpus quietly spans two standards.

### 4.2 The regression suite's 200 "expected bands" have no stated source

**Verified.** §6.10 and §12: *"200 frozen `(answer, expected band)` cases in CI"*, catching *"silent scoring drift from a prompt or model change"*. Nowhere says where a band comes from.

The tempting answer — snapshot the current model's output — freezes today's bias as tomorrow's ground truth, and every subsequent improvement reads as a regression. That is a trap worth naming in §3.1 alongside the other eight.

Say it: **bands come from human consensus, drawn from the calibration corpus.** Take 200 items where all three raters landed within one level after adjudication, set the band to `[min, max]` of the human scores, stamp `rubric_version`, and freeze. The suite then measures agreement with humans rather than self-consistency, and it can be rebuilt from the same data when a rubric version bumps.

Sequencing consequence: the regression suite cannot exist before annotation produces its first ~200 adjudicated items. §14 schedules it on day 11 and annotation on day 10. Part 8 fixes this by shipping the *harness* early and the *bands* when the data lands.

### 4.3 AC-13.3 is a P0 gate that cannot pass as written

**Verified.** *"Counterfactual name swap changes scores — target: 0"*, listed as **[GATE]**, i.e. blocking merge.

Two reasons it will flake. Sampling is not controllable on `claude-sonnet-5` or `claude-opus-5` (temperature/top_p removed — §2.6), so two runs of the *same* input can differ; a zero-delta assertion cannot distinguish a leak from ordinary variation. And the comparison is only meaningful when the names actually appear in the answer text, since §6.2 excludes identity by construction — which means the test is measuring content sensitivity to a token, not projection leakage.

Restate it as two gates that each test one thing:

- **AC-13.2 stays the leak gate** and it is exact, because it is structural: the type-graph walk over `EvaluatorView` and `PairwiseView`. Architectural tests can be 100%.
- **AC-13.3 becomes a statistical bias gate**: over ≥100 paired counterfactuals at a fixed `ensemble_config`, exact-match rate ≥ 0.9, mean signed delta within ±0.1 levels with a bootstrap 95% CI containing 0, and a sign test showing no systematic direction. Report the number; do not pretend it is zero.

The same correction applies to AC-13.4 (length-bias padding < 0.2 levels), which is already stated as a mean and just needs its `n` and CI published.

### 4.4 Two different quantities are both called length bias

**Verified.** §6.7's display gate uses `|length_bias_beta| < 0.15`; AC-13.4 and §12 use *"padded answers change the mean score by < 0.2 levels"*. The first is a regression coefficient in the calibration model; the second is a paired experimental effect. Neither states units.

Publish both definitions next to each other, because they answer different questions and you want both:

```
length_bias_beta   : coefficient on log(answer_token_count), in SCORE LEVELS per
                     natural-log unit of length, from the calibration regression
                     (score ~ raw + log_len + round_type). Gate: |beta| < 0.15.
padding_effect     : paired mean Δ in score levels over the 40-item padding set.
                     Gate: < 0.20 levels, with n and a bootstrap CI reported.
```

Without the units line, the 0.15 threshold is unfalsifiable — it means nothing until someone states what a unit of length is.

### 4.5 α ≥ 0.7 on 20 items is a coin flip

*(judgment.)* §6.6's training protocol gates progression on *"Krippendorff's α ≥ 0.7 on step 4"*, where step 4 is 20 gold items. Bootstrap CIs for α at n=20 with 3 raters are wide enough that a true α of 0.6 clears 0.7 fairly often and a true 0.8 fails it fairly often. Since the protocol's own remedy for failure is *"revise the anchors — the rubric is the problem, not the raters"* (which is the best sentence in §6.6), you want that decision to be driven by signal.

Cheapest fix: raise step 4 to 40 items and require the **lower bound** of a bootstrap 95% CI ≥ 0.6 alongside a point estimate ≥ 0.7. Roughly 40 extra minutes per rater, once.

### 4.6 The annotation labour is not budgeted anywhere

*(arithmetic, unverified against a real rater.)* §6.6: ≥800 turns × 3 raters = **2,400 ratings**. §8.2's own mock shows a 2:14 timer on item 47. At 2–3 minutes each that is **80–120 person-hours**, plus training (≈1.5 h × R) and adjudication. §8.2 says *"you'll spend 40 hours in it"*, which is roughly one rater's share, not the total.

Say the real number in §6.6 and size the panel from it: 6–8 raters at 12–18 hours each, over 3–4 weeks. Then check the assignment matrix is feasible — with R raters, every pair sharing ≥30 items needs `C(R,2) × 30` pair-slots; at R=6 that is 450 against 2,400 available, comfortable; at R=12 it is 1,980, tight. **R ≤ 8 is the constraint MFRM puts on recruitment**, and it is better known before you recruit than after.

### 4.7 Ethics is on the critical path and appears once, as an open decision

Covered in §1.5. Restating it here because of what it gates: §3.2.1 says *"Start recruiting and training raters in week 2, not month 4. This is the long pole of the entire project."* Recruitment cannot start before clearance, clearance takes weeks, and every displayed number in the product is behind the calibration study that is behind annotation. It is the single highest-leverage item in this review and it is not engineering work.

---

## Part 5 — Product, trust and the screens

- **AC-13.11 (dispute rate < 5%) is passed by hiding the button.** The same critique M04's review made of its own dispute metric. The honest pair is AC-13.12 (upheld rate) plus a *floor* on dispute visibility — the button is present on every score, always, which §2.2 already promises. Consider reframing AC-13.11 as a monitored signal rather than a gate: a *rising* dispute rate on one dimension is the most valuable quality alarm this module has, and a target that rewards suppressing it destroys the alarm.
- **EC-13.5 ("not assessable") has no UI state.** §8.1 lists `NoNumberNotice` for the uncalibrated case; a dimension that could not be assessed on *this answer* is a different message ("there wasn't anything here to judge") and rendering it as the calibration notice tells the student something false about the platform.
- **§8 is missing two required subsections** the other specs carry — all states (loading / empty / error / degraded) and mobile. The evidence drawer with audio playback on a phone is not a trivial adaptation, and the rater workbench is keyboard-first (`0-4` hotkeys per §8.2), which needs an explicit "desktop only" statement rather than a broken small-screen layout.
- **§2.2's mock renders `Correctness ●●●●○ 4/4`** — four filled dots out of five for a 4/4. On a 0–4 scale a perfect score is five dots. Small, but it is the module's headline mock and someone will implement it literally.
- **The "3 of 3 evaluations agreed" line changes meaning in degraded mode.** With N=1 it must not say "1 of 1 agreed" — it should say the run was single-evaluator and a fuller re-score is scheduled (§2.8). Write the copy; it is the sentence that keeps Practice mode honest.

---

## Part 6 — Cost, models and runtime

### 6.1 The cost table is dollars wearing a rupee symbol — it is off by ~75×

**Verified by arithmetic against master plan §47.2 and M06 §11.**

| Source | Ensemble N=3, per turn | Per ~25-turn session |
|---|---|---|
| M13 §11 | **₹0.034** | **₹0.9–1.1** |
| Master plan §47.2 | $0.85 / 25 turns = **$0.034** | **$0.85 ≈ ₹75** |
| M06 §11 | — | *"the bulk (≈ ₹81) is the evaluation ensemble, which is M13's budget"* |

The figure is identical and the symbol is not: `$0.034` per turn became `₹0.034` per turn. Master plan §47.2's own conversion (`$1.52 ≈ ₹134`) puts the rate at ₹88/$, so M13's session total is understated **~75×**.

Sanity-checking from first principles, with verified list prices (`claude-sonnet-5` $3/$15 per 1M; `claude-opus-5` $5/$25; cache reads ≈0.1× input):

```
one mid-tier evaluator, rubric prefix cached
  input   ~1,500 tok, ~80% cached  →  1200×$0.30/1M + 300×$3/1M  ≈ $0.0013
  output  ~700 tok (reasoning + 5 dimensions + spans)  →  700×$15/1M ≈ $0.0105
                                                        total ≈ $0.0118 ≈ ₹1.04
```

Which matches M13's own "₹0.011" to the digit — confirming the row is the dollar figure. The heterogeneous default (2 mid + 1 frontier) comes to ≈ $0.043 ≈ **₹3.8/turn**, ≈ **₹95/session**, consistent with M06's ₹81 and master plan's ₹75 (which assume an all-mid ensemble).

Rewrite §11 in rupees throughout. This matters beyond tidiness: §11's number is what the placement-cell licence conversation is priced from (master plan §47.2's free-tier economics), and a 75× error in the platform's single largest cost line is the kind of thing that gets found in a viva.

### 6.2 Prompt caching will silently not fill unless the prefix clears 1,024 tokens

**Verified against the caching reference.** §11 assumes *"rubric prefix cached"* in every evaluator row — it is the entire reason a single call is ~₹1 rather than ~₹4. The minimum cacheable prefix on `claude-sonnet-5` is **1,024 tokens**; below that the cache silently never fills (no error, `cache_creation_input_tokens: 0`), and the cost model is wrong by ~3× with nothing to indicate it.

A rubric with 5–7 dimensions × 5 anchors, plus scoring instructions and the output schema, will *probably* clear 1,024 — but "probably" is how M15 got the same note in its own plan. Do exactly what `IMPLEMENTATION_PLAN.md` §B.2 did: assert it with `count_tokens` in a test, and log `cache_read_input_tokens` per call so a cache that stops working is visible rather than merely expensive. Master plan §47.1 already makes cache-read ratio a tracked metric with a 0.5 floor treated as a bug — apply it here.

Two ordering consequences, both cheap and both easy to get wrong:

- **The permuted dimension order from §2.6 must sit *after* the last cache breakpoint**, or each ensemble member writes its own cache entry and reads none.
- **Nothing volatile above the breakpoint.** No timestamps, no turn ids, no candidate-scoped anything in the system block. §6.2's projection already excludes session metadata, which helps — but the *ordering* has to be enforced in the prompt builder, not assumed.

### 6.3 One routing rule to state explicitly

Master plan §47.1 rule 1: *"Anything a student sees as a score is evaluated at mid tier or above, never cheap."* M13's ensemble complies. Two places it could quietly stop complying — the degraded ladder (§6.4's "N drops to 2 then 1" must drop *count*, never *tier*; master plan §47.2's lever list says the same: *"We do not lower the tier of scored evaluation to save money"*) and the fact-check step (§6.4 step 2, "mid tier + retrieval") which feeds a scoring decision. Write both as rules in §11 so a later cost squeeze cannot take them.

The adjudicator and the pairwise judge are also student-visible scores and belong at frontier and mid-or-above respectively; §6.4 has this right, and it is worth saying why so nobody re-tiers it.

### 6.4 What is already right and should not be touched

Batch API at 50% for the nightly research re-score (§6.4, §11) matches master plan §47.1 exactly. Async-by-default and never on the hot path (FR-13.19) matches M06 §6.2's `enqueue(evaluate_turn, ...)`. Self-hosted NLI and local models match §47.1's local tier. No changes needed.

---

## Part 7 — Test plan and gates

The adversarial suite (§12) is the best test table in the spec set and needs only additions:

| Add | Asserts |
|---|---|
| Injection **mid-answer**, with a genuine quote after it | Offsets survive neutralisation (§2.2) |
| A fuzzy-repaired span | Stored `quote` equals `artifact[start:end]`, not the model's text (§2.1) |
| Same answer, dimension order permuted | Mean score Δ < 0.1 levels — proves the decorrelation in §2.6 is rubric-neutral |
| Two evaluators returning identical output | `spread=0` recorded and *not* rendered as high confidence (§2.10) |
| Hinted vs unhinted correct answer | `raw_score` identical; credited score differs by the published factor (§1.4) |
| Rubric with two `concept_bearing` dimensions | Fails to load (§1.2) |
| Rubric with a missing anchor level | Fails to load (existing unit test — keep) |
| An answer scored under a `push_back` rubric | Agreement with the interviewer is a note, not a penalty (EC-13.10) |
| Delivery vector with a `coaching`-disposition signal | It contributes to no numeric (§3.2, AC-13.17) |
| A `TurnEvaluation` field sourced from an integrity signal | CI dependency check fails (§3.5, mirrors M18) |

Gate changes, consolidated:

- **AC-13.2** stays exact (architectural), and now covers `PairwiseView` too.
- **AC-13.3** becomes statistical with a stated `n` and CI (§4.3).
- **AC-13.16 [new, GATE]** every stored span satisfies `artifact[start:end] == quote` (§2.1).
- **AC-13.15 [new, GATE]** no peer rater receives un-transformed audio (§1.5).
- **AC-13.17 [new, GATE]** no non-`scored` delivery signal contributes to a numeric (§3.2).
- **AC-13.11** demoted from gate to monitored signal (§5).

---

## Part 8 — Revised build order

§14's 14 days is really ~19. Adds: contracts and the fixture seam **+2**, observation emit + hint policy **+1**, evidence-repair and injection corrections **+0.5**, consent/de-identification in the workbench **+1**, dispute review surface **+0.5**, ensemble decorrelation + cache assertions **+0.5**. Removes: nothing — the original list is all load-bearing.

Restructured so **M13 clones and runs alone** (no day depends on M05 or M12 existing) and so the two calendar dependencies — ethics clearance and rater recruitment — start on day 1 rather than day 9.

| Milestone | Days | Demoable outcome |
|---|---|---|
| **M0 — Contracts & the seam** | 1–2 | `ai_core` types consumed (`EvidenceSpan`, `EvidenceRef`, `VersionStamp`); `RubricDimension.concept_bearing`; hint-penalty table published; `/health` + `/v1/deps` green; `module.json`; question/delivery adapters with fixtures. **Ethics annexe filed. Rater recruitment opened.** |
| **M1 — Rubrics** | 2–4 | Typed rubric schema with anchors, `AppliesWhen`, disqualifier flags; 3 dimensions for `dsa_verbal` authored; anchor-completeness and single-`concept_bearing` tests. |
| **M2 — Blind projection** | 4–5 | `EvaluatorView` + `PairwiseView`, both architectural leak tests in CI. **AC-13.2 green on day 5.** |
| **M3 — One evaluator, end to end** | 5–7 | Structured output with `enum` scores and enumerated artifact ids; **span verification + repair-with-overwrite + reject/retry**; artifact snapshot + checksum; injection neutralisation. **AC-13.16 green.** |
| **M4 — Ensemble** | 7–9 | N=3 heterogeneous with the order-permutation decorrelator, aggregation, `spread_levels`, adjudicator; cache-prefix `count_tokens` assertion + cache-read telemetry. |
| **M5 — Emit** | 9–10 | NLI coverage (local); observation batch emit to M04 with uuid5 idempotency + outbox; M02 coverage-ledger write; retract-on-rescore. **M04's map moves from a real answer.** |
| **M6 — Rater workbench** | 10–12 | De-identified audio, anchors at the point of decision, keyboard rating, gold interleaving, `HumanRating` with all three MFRM facets. **AC-13.15 green.** |
| **M7 — Annotation begins** | 12 → ongoing | Guidelines + 50 gold items + the 40-item training gate. Runs in the background from here. |
| **M8 — Meta-evaluation** | 12–14 | Adversarial suite in CI (bands from the first adjudicated items, not from the model); length-bias and sycophancy harnesses; regression *harness* shipped, bands backfilled as annotation lands. |
| **M9 — Calibration & gate** | 14–16 | Platt/isotonic fitting keyed on `(dimension, round_type, ensemble_config)`; display gate at render time; composite rule with the `None` clause. |
| **M10 — Trust surfaces** | 16–19 | Evidence drawer with playback, key-point checklist, confidence badge, no-number notice, dispute dialog + queue + resolve + M04 re-test wiring. Fact-check path. |
| *(ongoing)* | | MFRM analysis, bias audit tooling, pairwise/BT for communication. |

The reordering that matters most: **the observation emit moves from "never" to day 9**, and **annotation starts on day 12 instead of day 10 of a 14-day plan** — which only works because recruitment and ethics started on day 1.

---

## Part 9 — Cut list

In order of least regret:

1. **Pairwise / Bradley–Terry (§6.5) → Phase 2.** It is P1, it needs its own blind projection (§2.3), and its head-to-head against absolute scoring is only meaningful *after* the first agreement study says where absolute scoring is weak — which §15.4 already concedes. Ship the absolute path, publish the agreement numbers, then decide. Keeps Paper 1's headline comparison intact and moves ~2 days out of Phase 1.
2. **Fact-check (§6.4 step 2) → after the first agreement study.** It is P1 and it costs the most per turn of anything in §11. Its job — never mark a correct-but-unfamiliar answer wrong — is *also* served by the rubric instruction (*"the reference is a good answer, not the good answer"*), which is free. Measure how often EC-13.2 actually fires before buying retrieval infrastructure for it. Keep the `reference_may_be_incomplete` flag and the reference-review queue: those are cheap and they improve the item bank.
3. **`DisputeDialog` UI → Phase 2; endpoint, queue and pending state in Phase 1.** Same call M04's review made. The trust defence that actually carries §2.3 is the evidence drawer plus the scheduled re-test, and both survive.
4. **Phase 1 rubric set 6 → 4.** §6.1 lists `dsa_verbal`, `dsa_coding`, `cs_core`, `project_defence`, `behavioural_star`, `communication`. Writing good anchors is, by §3.2.5's own admission, *"the highest-leverage authoring work in the project"* and it is slow. Four (`dsa_verbal`, `dsa_coding`, `cs_core`, `communication`) cover what M05 can seed and what M06 will actually run in Phase 1; the other two are a YAML append.
5. **The N=1 practice-mode calibration (§2.8) → suppress and backfill.** Cheaper than fitting a second calibration and more honest to the student.

**Do not cut:** the rater workbench, the display gate, or the adversarial suite. The first is the long pole's only tool, the second is the module's entire credibility argument, and the third is the only thing standing between a prompt tweak and silent score drift.

---

## Part 10 — Open decisions (replaces §15)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Ensemble composition | **Heterogeneous by default, and it is no longer optional** — with no sampling knob on Sonnet 5/Opus 5, a homogeneous ensemble is one sample with extra steps (§2.6). Keep §15.1's Month-4 experiment, but run it as *"does the third call buy anything"*, not *"mid vs frontier"*. |
| 2 | Who are the raters? | **(c) both**, as §15.2 says — with the addition that peers see **de-identified** audio and only faculty may see identity, with a logged reason (§1.5). |
| 3 | Show a composite before calibration passes? | **No** (§15.3 was right), and now with a mechanism: `composite is None` if any contributing dimension is display-suppressed (§2.16). |
| 4 | Pairwise for which dimensions? | **Defer the whole path to Phase 2** (Part 9), then decide from the agreement study rather than from a proposal. |
| 5 | Disqualifiers | **§15.5's policy is right; make it structural** — a flag with evidence, no field through which it could zero a score (§2.17). |
| 6 | **New** — what is the hint penalty? | Publish the table in §6.1, apply it to the credited score only, show it to the student (§1.4). |
| 7 | **New** — who owns the 2-day dispute SLA? | Needs a name and a rota before §2.3's copy ships (§3.3). |
| 8 | **New** — which dimension is concept-bearing per round type? | `correctness` by default; `communication` maps only to communication concepts. Write it into every rubric and test it (§1.2). |
| 9 | **New** — does the calibration corpus include scaffold-less runs? | Stratify on `scaffold_used`, or exclude them from the fit (§2.11). |

---

## What I would do first

Three days, in this order:

1. **File the ethics annexe and open rater recruitment.** Not engineering, longest lead time, gates everything numeric in the product. Day 1, before any code.
2. **Part 1's six contracts** — platform evidence types, the M04 observation emit with `concept_bearing`, `VersionStamp`, the hint table, consent columns, key-point ownership. Two days, and every one of them is a migration once M05 and M06 are writing against M13.
3. **Fix §6.3's repair path and EC-13.3's stripping.** Half a day, and they are the two places where this module could produce something that is *confidently wrong about the student's own words* — which is the exact failure §1 says is worse than no score at all.

The rest of Part 2 is real but findable once the adversarial suite exists, which is why Part 8 keeps it early and keeps it in CI.

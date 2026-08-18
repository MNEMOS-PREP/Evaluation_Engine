# M13 — what other modules get, and what they must send

> Read this before wiring a sibling module to M13. Every shape below is
> asserted by a test in `tests/test_contracts.py`, so if one of them changes,
> the break appears in *this* repo rather than in yours.
>
> Endpoints named here were checked against the other module's **shipped
> router**, not against its spec. Two of them differ from what the plan said.

---

## The one rule that governs everything here

**M13 never blocks on you, and you never block on M13.**

Every outbound artifact goes through an outbox: it is written in the same
transaction as the evaluation and drained afterwards. If your module is down,
a mastery update is delayed. A student's score is not lost, and their
evaluation does not fail. This is the one promise this module cannot break,
so nothing below is a synchronous call from the scoring path.

---

## 1 · M04 — Skill Graph & Memory  *(the mastery write path)*

**M13 sends. M04 stores. This is the only way mastery changes.**

```
POST {M04}/v1/candidates/{candidate_id}/observations
Header: X-Service-Secret
Body:   {"observations": [ … ]}          ← a LIST, one transaction
```

Not `/v1/observations` — that path does not exist. M04's write path is
per-candidate and batched, because its 60ms budget is per call rather than per
observation.

### Which score becomes mastery

Exactly one rubric dimension is `concept_bearing`, and only that dimension's
score reaches technical concepts. `communication`-domain dimensions reach
communication concepts and nothing else. `depth` produces **no observation at
all** — it is a score a student reads, not a separate belief about a concept.

Get this wrong and communication quality silently becomes part of technical
mastery, inside θ, where nobody can untangle it afterwards. The rubric loader
refuses to load a rubric declaring zero or two concept-bearing dimensions.

### Fields you can rely on

| field | note |
|---|---|
| `id` | `uuid5(OBS_NAMESPACE, "{turn}\|{concept}\|{kind}\|{rubric_version}")` — **M04's own formula.** Insert on conflict-do-nothing; a replay is a no-op, not a second answer. |
| `raw_category` / `n_categories` | The un-normalised ordinal, 0..4. **This is the GRM likelihood input.** |
| `outcome` | Normalised 0–1. Display and BKT only — explicitly *not* the likelihood. |
| `response_model` | `grm` when a calibrated item exists, `none` otherwise. |
| `item` | `None` while M05 is absent → **not θ-eligible**, so M04 updates counts and evidence and leaves θ alone. |
| `source_dimension_key` | Which dimension produced this. Auditable by design. |
| `weight` | `0.7` for a hint-assisted answer. Applied **once, here**; M04 does not re-apply. |
| `evidence` | ≥1 `EvidenceRef`, each verified and checksummed. M04 rejects a write whose evidence does not resolve. |
| `consent_id` | **Required, no default.** Resolve consent at session start (M6), not at scoring time. |
| `versions` | `ai_core.versions.VersionStamp`, full. |

### Disputes and re-tests

```
POST {M04}/v1/candidates/{cid}/mastery/{concept_id}/dispute
```

**M04 owns the `retest_queue` row.** M13 asks for a dispute; M04 enqueues,
including `bypass_freshness` so M05's 90-day no-repeat filter cannot silently
make the promise empty. M13 does not write another module's table.

### Re-scores retract, they do not compensate

A re-score appends a new evaluation, points the old one at it, and **retracts**
the superseded observation. M04 recomputes mastery from surviving
observations, so an inverse update would be a second belief about the same
answer rather than the removal of the first.

---

## 2 · M02 — JD Parser & Coverage Planner

M13 emits the coverage transition that M02 §6 calls *"the mechanism that makes
coverage a guarantee rather than an intention"*.

```json
{ "turn_id": "…", "session_id": "…", "state": "scored",
  "score": 3.0, "n_categories": 5, "rubric_version": "1.0.0", "scored_at": "…" }
```

`score` is the **concept-bearing** dimension. A requirement is covered by
whether the candidate could do the thing, not by how well they narrated it.

---

## 3 · M19 — Reports & Evidence Ledger

One `LedgerEntry` per dimension score, in M19 §5's shape:

```json
{ "claim_kind": "dimension_score", "claim_key": "correctness", "value": 3.0,
  "evidence": [ … ], "versions": { …, "code_sha": "…" }, "computed_at": "…" }
```

Append-only. A re-score inserts new entries; the old ones stay, which is what
makes *"re-scored under rubric v2.1"* something the product can say out loud.

**Whether M19 may render a number is not M19's call.** Read the display gate:

```
GET /v1/calibration    → per (dimension, round_type, ensemble_config):
                         display_numeric, and gate_reasons in plain words
```

`display_numeric: false` means show the reasoning and **no number**, with the
§2.4 note. Today it is false everywhere, because no calibration is fitted.

---

## 4 · M16 — Counselor  ·  M17 — Communication Coach

Both read `TurnEvaluation` directly.

- **M16** — compare only within a compatible version window. `VersionStamp.comparable_to()` in `ai_core.versions` is the check: rubric, calibration and item bank sever comparability; prompt, model and `code_sha` do not.
- **M17** — `key_point_coverage` (per key point, 0–1) plus `aggregated[].evidence` spans with character offsets. `t_ms` is derived from M11's word alignment at read time, so a re-alignment updates playback without invalidating a stored span.

---

## 5 · What M13 needs from you

Both enter through an adapter with a fixture implementation, so M13 runs
standalone today and swapping in the real module is a config change.

### M05 — Question Intelligence

```python
QuestionPackage(question_id, stem, reference_answer,
                key_points=[KeyPoint(id, statement, weight, required)],
                round_type, concepts={concept_id: weight},
                item=ItemParams(...) | None)
```

`item=None` is fine and honest — it just means the resulting observation is not
eligible to move an ability estimate.

### M12 — Multimodal Suite

Send `FusedAssessment`, **not** a `dict[str, float]`. Flattening drops
`disposition`, and M12's own P0 validity gate — no signal is `scored` without a
completed validity record — stops being enforceable one module downstream.
M13 asserts it: only `scored` signals may reach a numeric.

A signal with no recorded disposition is treated as **not** scored.

---

## Trying it before either side is wired

```
GET /v1/evaluations/{turn_id}/outbound
```

Returns exactly what that evaluation owes M04, M02 and M19 — real shapes, real
ids, real evidence — so you can build against it before anything is connected.

```
GET  /v1/outbox          what is queued, and why anything failed
POST /v1/outbox/drain    push it to M04; idempotent, safe to repeat
```

---

## Known gaps, stated plainly

| Gap | Consequence |
|---|---|
| No calibration is fitted | `display_numeric` is false everywhere and `composite` is `None`. **No number is student-facing.** Gated on the annotation study, not on code. |
| Rater workbench is API-only | `AC-13.15` (de-identified audio for peer raters) is not met; the queue returns ids, not content, until it is. |
| No frontend | Port 5213 reserved. The evidence drawer is served as JSON by `/evidence`. |
| Fact-check (FR-13.10) deferred | P1. The rubric instruction "the reference is *a* good answer" carries EC-13.2 for now. |
| Pairwise / Bradley–Terry deferred | P1, Phase 2. `PairwiseView` and its blindness gate exist; the fitting does not. |
| Free-tier scores are `dev` grade | Real evaluations with real verified evidence, excluded from the display gate and the calibration corpus **by their grade**, not by anyone's discipline. |

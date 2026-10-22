# M13 — TODO · Evaluation Engine


> **Completion: 98%** — 20 of 21 functional requirements met, 1 partially. Every requirement has shipped code. The one incomplete: the human-rating queue has no test. The M02 ledger write the 2026-08-28 audit found **built but never sent** has been delivered since 2026-09-23 — `delivery.py`'s sweeper, on `ai_core.outbox`, sends both channels (M04's observations, M02's coverage) on an interval and on every new evaluation. FR-13.21 degrades rather than blocks, because M12 is `required: false`.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28; re-checked 2026-10-04: the ledger gap is closed (95% → 98%); re-checked 2026-10-17: unchanged — reviewers can now rate, and the raters' queue still has no test of its own. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Running list for **M13 Evaluation Engine**.
Spec: [M13_Evaluation_Engine.md](M13_Evaluation_Engine.md)

> **Read this first when starting a session on M13.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1 · **Owner:** E1 · **Ports:** API `8113`, web `5213`
- **Repo:** `Evaluation_Engine`

Legend: ✅ done · 🟡 partly done · ⬜ not started

### 2026-10-23 — whole questions from M06, and the help they needed (`f673f90`)

M06 now asks one thing at a time and pushes back on wrong answers, so a
question is a thread of answers. M13 scores the thread once, when it closes
(M06's realism overhaul — `Mock_Interview_Engine/plan_in_depth/M06_OVERHAUL.md`).

- ✅ **`prompts_used`**: the interviewer's corrective pushes before an answer
  came right, priced with the rubric's own published hint credit — a correct
  answer and one that got there with help no longer score alike.
- ✅ **`key_point_ids`**: the key points of what was actually asked, for a
  question asked one part at a time; absent means all of them, and an empty
  match never judges an answer against nothing.
- ✅ **Help past the table holds the last price** — "unlisted levels credit
  fully" was a refund once hints and pushes could add up.
- ✅ **Prompt `m13-eval-1.1.0`**, rule 7: one question's several answers are
  scored as the understanding they show together, a correction named as one.
- ✅ **The checklist is the evaluators'** (below, 2026-10-22).
- Tests: `test_threads.py` (7) — 187 in all, lint clean.

### 2026-10-22 — how an answer is scored on this machine, and a checklist that contradicts the evaluators

An audit for the demo, against `77ead37`. No code changed.

- ✅ **The checklist under a strong answer is wrong.** `service.py` (~L209)
  fills a dimension's `missing_key_points` from the coverage measure whenever
  the ensemble listed none. With the lexical fallback, a correct paraphrase of
  M05's `hashing_average_lookup` ("compute a hash of the key and jump straight
  to that slot … spread evenly … resized before it gets too full … if
  everything collides it becomes linear") scores 0.14 / 0.00 / 0.00: all three
  points "missing", under an answer the evaluators would call complete. Fix:
  keep the evaluators' empty list as final, and use coverage only when no
  evaluator produced one, with the paraphrase as the test — or install NLI
  (below). The comment above that line says the checklist comes "from the
  coverage measure", which the code does not do; reconcile them. Owner's call;
  not changed. _Fixed 2026-10-23 (`f673f90`): the evaluators' list is final, an
  empty one meaning nothing is missing; coverage still scaffolds them and stays
  on the evaluation (`key_point_coverage`). Test: `test_threads.py`._
- ⬜ **Key-point coverage is the lexical fallback here.** M13's venv has no
  `transformers` or `torch`, so DeBERTa-MNLI never loads, and the scaffold the
  evaluators see is word overlap (`KP_LEXICAL_ABSENT_BELOW` 0.2, threshold
  version 1.1).
- ⬜ **Scores run on the dev grade.** `projects/keys.txt` has no
  `ANTHROPIC_API_KEY`, so `get_llm()` uses Groq `openai/gpt-oss-120b`: real
  scores with verified evidence, `ScoreGrade.dev`, never displayable and never
  in the calibration corpus. And `n3_het_v1`'s three members are all
  `model=None` — one model three times, decorrelated only by dimension order
  (seeds 0/17/41). Heterogeneous needs a second provider.
- Only reviewed M05 items reach M13 (M06 does not send drafts), and only 12 are
  reviewed, all DSA — see M05's TODO, 2026-10-22.

### 2026-10-17 — a decision: two keys, two organizations?

- ⬜ **Key rotation and Groq's policy — the user's call.** `llm.py` takes the
  next of the two `GROQ_API_KEYS` on every attempt. Measured on 2026-10-17,
  the keys have **separate quotas** (8,000 tokens/min and 1,000 requests/day
  each, per model); Groq applies limits per organization, so they are almost
  certainly two organizations, and Groq's Acceptable Use Policy (effective
  2025-10-15) forbids "orchestrating usage between multiple organizations" to
  go beyond rate limits. If so: one key per running platform, headroom from
  spreading across models and pacing. Recorded in full in M06's TODO.

### 2026-10-13/16 — reviewers rate, and words the officers can trust

- ✅ **A reviewer submits human ratings as themselves** (`e816846`, abhinav):
  the `reviewer` role may post a rating, the rater is pinned to the signed-in
  subject rather than the body's, and the role reaches nothing else
  (`test_a_reviewer_rates_as_themselves_and_reaches_nothing_else`). The
  raters' queue itself still has no test, so the header's one partial stands.
- ✅ **Platform_Core v0.38.0** (`8188e07`): the rating routes read
  `Role.reviewer`, which the pinned v0.12.0 lacked, so M13 failed to start.
- ✅ **The bench and rubric pages say what is true** (`e48f167`): the bench
  promised that with M05 running its questions would come from the live bank,
  but it only ever reads the fixture set, and now says so. "So M04 does not
  deduct again" names the skill graph, and the disqualifier note no longer
  routes to M18's fabrication probe, which does not exist.
- ✅ The outbound page has a key for an observation not yet sent (`41c6041`);
  the dispute dialog's backdrop fades in and its panel rises (`95430b2`).
- ⬜ **AC-13.15 [GATE] — de-identification before any peer rates an answer.**
  The workbench must serve pseudonymised transcripts (and transformed audio)
  to peer raters. Until it does, a reviewer can rate but the workbench cannot
  show them the answer, so the human-agreement metric cannot start. Cheap now
  and impossible to retrofit once ratings exist against raw answers (§6.6).

### 2026-10-07/08 — a rubric for every track; the concept the ontology calls hashing

- ✅ **Rubrics for every track M05 offers** (`fcbabcc`): a rubric document may
  list `round_types`, and `technical_verbal.yaml` registers one rubric (what
  they said is right, they know why, a peer could follow it) under the seven
  core-CS and ML tracks, each with its own id; `behavioural.yaml` scores HR
  rounds. DSA keeps its own anchors.
- ✅ **The fixture bank said `concept:hash_maps`; M04's ontology says
  `concept:hashing`** (`ec159d3`). Every observation from the fallback bank
  was refused as an unknown concept and sat in the outbox — 8 of the 14 rows
  the staff Today page showed as stuck. A test now reads M04's ontology beside
  this repo and checks every fixture concept is in it.
  ⬜ **The 14 rows already refused need an operator to void them** — staff
  action, not code.
- ✅ The rubrics page fits a phone with nine rubrics (`bd52acc`).

### 2026-10-04 — the evidence page talks to a student

- ✅ **The lexical fallback stops calling paraphrased key points missing.** With
  no NLI model, coverage is word overlap, and it was held to the entailment
  bar (0.5): a correct paraphrase shares under half a key point's words, so a
  complete answer read "Not covered yet" three times. The lexical measure has
  its own bar now (`KP_LEXICAL_ABSENT_BELOW = 0.2`); the NLI model keeps 0.5.
  `KP_THRESHOLD_VERSION` 1.1, because it changes checklists.
- ✅ **The evidence page in a student's words**: "How your answer was marked",
  "your exact words", "second opinion taken". The calibration vocabulary and
  bare key-point ids are for dev mode.
- ✅ The dispute-queue and outbox hooks are exported, so an administrator's
  first page counts open disputes and stuck rows.
- ✅ (2026-10-03) M13's buttons have labels again — `Btn` dropped its children,
  and eighteen buttons drew as empty pills. Found from a screenshot.

### 2026-09-17 — the M05 seam is wired

Found while building M06: `adapters.get_questions()` was **always**
`FixtureQuestions`, and there was no HTTP implementation of `QuestionSource`
anywhere — so `POST /v1/evaluations` answered **404 for every real M05
question id**, and no question from the live bank could be scored by anybody.
That is the Phase-1 exit gate, not a convenience.

`LiveQuestions` now calls `GET {M05}/v1/questions/{id}/package?round_type=`
(the route M05 already built for this), wired at startup from `module.json`,
with the fixture bank behind it so the regression suite and `question_label`
still resolve and a fresh clone still runs alone. `QuestionSource.get()` takes
the administered `round_type`, because M05 requires it and every caller here
knows it.

**Still open, and the same class of gap:** the M04 observation emit has no
HTTP client either — `emit.py` assembles the payload and nothing delivers it,
so the outbox has rows and no transport. M06 will start filling that outbox
with real turns. **Closed 2026-09-23:** `delivery.py`'s sweeper delivers it; see §1.

### 2026-10-03 — the key file beside the repos

- ✅ **`keys.py` reads the `keys.txt` beside the repos** (and `AI_KEYS_FILE`).
  It read only Backend/ and the repo root, so on a fresh demo machine — one
  shared key file, as M02 and M06 expect — M13 found no model and scored
  nothing. `test_keys_location.py`; `start.bat` now says where each module
  finds its key.

### 2026-10-03 — Platform_Core v0.12.0: roles, the service secret, the playground

- ✅ **The operator's routes take `Role.admin`** (`require_role`): the outbox
  and its drain and requeue, the dispute queue and its resolve, human ratings
  and the raters' queue. `assert_staff_only` finds all seven from the OpenAPI
  document. Researchers are not let in: rating a turn means reading the
  answer, and a researcher sees cohorts only.
- ✅ **Who resolved a dispute is who is signed in**, not the `resolved_by`
  the body carried (the screen sent "unknown").
- ✅ **M05 is asked as a module.** M05 now serves its answer key only with the
  platform secret; `LiveQuestions` sends `ai_core.service.headers()`, as
  `emit.py` does for M04. Without it every live item would 401 and fall
  through to "no package".
- ✅ **Found: the playground 403'd in the shell.** `POST /evaluations` with
  no `candidate_id` defaulted to a random one, which the v0.11.0 guard then
  refused as somebody else's. Absent now means the student asking.
- ✅ **Frontend on the platform session**: standalone signs in as the
  operator only when nobody is signed in.

### 2026-10-02 — asks from M06

- ⬜ **M06's notes now show a student three of M13's fields** (M06 day 12):
  each dimension's `reasoning`, its `missing_key_points`, and the quotes of
  *verified* evidence spans — never a number; those stay behind the display
  gate. State in the contract that these fields are student-visible, so their
  wording is held to that standard (nothing that telegraphs, nothing like
  "you should know this"). The evidence drawer is student-facing too, so this
  may already be true — make it a rule rather than a coincidence.
- ⬜ (standing) Code and canvas artifacts get a fresh `uuid4()` per evaluation,
  so they can never resolve in M04 the way a transcript does.
- **Confirmed live** (2026-10-02, M04's guard on): four evaluations scored from
  M06's outbox; the scored channel reached M02; observations reached M04 and
  moved hashing, time complexity and hashing internals to `emerging`.
- ⬜ (standing) A `push_back` rubric variant. It unblocks M06's FR-6.20
  (steelman probes), which stay off everywhere until it exists.
- ⬜ (standing) `cs_core` and `communication` rubrics. The second would also
  let M06 score the student's own closing questions (FR-6.21).

### 2026-10-02 — who may ask, and the ledger's new address

- ✅ **Platform_Core v0.10.0 → v0.11.0** on both halves.
- ✅ **`candidate_guard` on the router — M13 had none.** A student's
  evaluation, its evidence and the exact request sent to the evaluators were
  readable by anyone holding a turn id. Routes now resolve a turn or
  evaluation id to its student, and `POST /evaluations` checks the student
  its body names. `tests/test_guard.py` covers it, and removing the guard
  fails three of its tests. The suite's own client is staff, as in M04 and M15.
- ✅ **The standalone frontend is the operator's console** and says so with
  an admin dev identity. Inside the shell the identity is the student's, as
  it should be.
- ✅ **The scored channel posts to `/v1/coverage/...`**, M02's own noun now
  (`sessions` is M05's in the shell).
- ✅ **The dispute queue, human ratings and outbox actions check no role** —
  fixed 2026-10-03, see above. No per-request role was needed: the shell's
  sign-in sets one session for the page, and an operator signs in as one.

---

## 0. Ideas and scouting

Things worth building that did not come from the spec — usually from reading
somebody else's implementation. **New ideas go at the top of this section.**

The rule we keep arriving at: borrow a **technique**, not a **component**. The
platform's contracts — character offsets, per-fact provenance, permanent
evidence — are more demanding than general-purpose tools assume, so integration
usually costs more than reimplementing the one idea we actually wanted.

_Nothing scouted for this module yet._

---

## 1. Where the module stands

| | |
|---|---|
| Status | **Built.** FR coverage was audited on 2026-08-28 and re-checked on 2026-10-04 and 2026-10-17 (the header). The per-requirement table was never written into this file, and the §13 acceptance gates have not been walked one by one |
| Backend tests passing | **180** |
| Release gates (`-m gate`) | **31** |
| Frontend | the operator's console standalone; in the shell, the student's "How your answer was marked" page and the staff queues |

*Counted 2026-10-17 by running the suite, not by reading this file.*

> **Re-checked 2026-10-04:** the ledger gap the 2026-08-28 audit found is
> closed. Since 2026-09-23 `delivery.py`'s sweeper (on `ai_core.outbox`)
> delivers both channels — M04's observations and M02's coverage — on an
> interval and on every new evaluation. `POST /v1/outbox/drain` is the
> operator's safety net now, not the mechanism.

---

## 2. Next

1. **A test for the human-rating queue** — the last partial requirement.
2. **AC-13.15, de-identification for peer raters** — the gate the human-agreement metric waits on (see 2026-10-13/16 above).
3. **Walk the §13 acceptance gates** one at a time and write what each needs here.
4. M19's ledger channel and its backfill, when M19 exists (see `delivery.py`).

---

## 3. Deferred — inter-module

Not gaps in M13. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._

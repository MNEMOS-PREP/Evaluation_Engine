# M13 — TODO · Evaluation Engine


> **Completion: 95%** — 19 of 21 functional requirements met, 2 partially. Every requirement has shipped code. Two are incomplete rather than absent: the human-rating queue has no test, and the M02 ledger write is **built but never sent** — `emit.py` assembles the payload and the module contains no HTTP client to deliver it, so the outbox has rows and no transport. FR-13.21 degrades rather than blocks, because M12 is `required: false`.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Running list for **M13 Evaluation Engine**.
Spec: [M13_Evaluation_Engine.md](M13_Evaluation_Engine.md)

> **Read this first when starting a session on M13.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1 · **Owner:** E1 · **Ports:** API `8113`, web `5213`
- **Repo:** `Evaluation_Engine`

Legend: ✅ done · 🟡 partly done · ⬜ not started

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
with real turns.

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
| Status | **Built, and not yet audited against the spec.** |
| Backend tests passing | **135** |
| Release gates (`-m gate`) | **25** |
| Route decorators | **20** |
| Frontend | present |

*Counted 2026-08-25, by running the suite — not by reading this file. This row
replaced "Not started", which was written before the module was and had become
the kind of line the header above warns about: the next session trusts it.*

> **What has NOT been done is the audit.** Nobody has walked M13's functional
> requirements one at a time and checked each against the code. A green suite
> says the tests that exist pass; it does not say which requirements have tests.
> M01 learned that the expensive way — its FR table read 98% complete while the
> §13 KPI had no numerator, the semantic tier was absent and ten endpoints had
> no client. Every one of those was invisible from a passing suite.
>
> The next session on M13 should start there, and write what it finds here.
| Spec | Written — see the link above |

_Fill this in when work on M13 begins: tests passing, gates, FR coverage,
and what is actually blocking._

---

## 2. Next

_To fill in._ The spec's §4 functional requirements and §13 acceptance
gates are the natural first pass — copy them in as a checklist, then mark what
already exists.

---

## 3. Deferred — inter-module

Not gaps in M13. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._

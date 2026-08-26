# M13 — TODO · Evaluation Engine

Running list for **M13 Evaluation Engine**.
Spec: [M13_Evaluation_Engine.md](M13_Evaluation_Engine.md)

> **Read this first when starting a session on M13.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1 · **Owner:** E1 · **Ports:** API `8113`, web `5213`
- **Repo:** `Evaluation_Engine`

Legend: ✅ done · 🟡 partly done · ⬜ not started

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

# `Frontend/`

Vite + React 19 + TypeScript, Tailwind v4, TanStack Query, organised as **npm
workspaces**. Stack decisions are in `AI_Interviewer_Master_Plan.md` §20.

```bash
npm install                                     # ONE install for every workspace
npm run dev                                     # M13 on :5213 (PORTS.txt)
npm run build
npx tsc --noEmit -p tsconfig.base.json
```

The dev server proxies `/v1` and `/health` to the backend on `:8113`, so the
browser sees one origin and there is no CORS to think about. Point it at the
platform gateway instead with `VITE_API_BASE=http://127.0.0.1:8000`.

## Layout

```
frontend_M13_Evaluation_Engine/
  src/types.ts           the backend's shapes, mirrored field-for-field
  src/api.ts             one hook per endpoint, and no hook without one
  src/routes.tsx         keyed on turn_id, not evaluation id
  src/components/
    ScoreBench.tsx       the way in while M05 and M06 are absent
    TurnPage.tsx         the answer, and what it earned
    Transcript.tsx       offsets → highlights. Read this one first.
    Judgement.tsx        the ONLY place that decides a number may be shown
    …                    rubrics, calibration, disputes, raters, outbox, deps
  src/ui/                theme, primitives, shell, the view switch
```

## The three rules this UI exists to keep

**1. No number until it is earned.** `calibrated_score` is null unless a fitted
mapping cleared every threshold in §6.7. Null means the dimension renders its
reasoning and its evidence and *no number* — not a dash, not a greyed digit,
not the raw score "just for now". [`Judgement.tsx`](frontend_M13_Evaluation_Engine/src/components/Judgement.tsx)
is the single place that decides this, because a gate applied by seven
components is a gate six of them apply and the seventh forgets.

Today it is closed everywhere. That is the honest state, not a missing feature:
see `/calibration`, which lists every threshold and why.

**2. A highlight is never approximate.** A span is a pair of offsets, and
[`Transcript.tsx`](frontend_M13_Evaluation_Engine/src/components/Transcript.tsx)
slices the frozen artifact with them. It refuses to highlight when the stored
text fails its checksum, and drops any individual span whose slice does not
equal its quote. Painting it at roughly the right place would underline words
the student did not say and caption them "what you said" — worse than showing
no evidence at all, because it looks like proof.

**3. `agreement`, never `model_confidence`.** The badge is derived from spread
across independent evaluators. The model's opinion of itself feeds ECE, is
visible only in the developer view, and is never a student-facing signal.

## Student view vs developer view

A real switch in the header, not a disclaimer beside a number — people read the
number and skip the disclaimer. Student is the default and the gate applies;
developer shows raw 0–4, spread, seeds, tokens and cost. A bug report can carry
its view: `?dev=1`.

## Adding another module frontend

Copy `frontend_M13_Evaluation_Engine/`'s `package.json`, `vite.config.ts`,
`tsconfig.json` and `index.html`, change the name and the port (see
`PORTS.txt`), then add its routes to the shell. The `frontend_*` workspace glob
picks it up with no config change.

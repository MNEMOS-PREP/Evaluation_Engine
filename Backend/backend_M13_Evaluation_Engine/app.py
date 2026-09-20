"""M13 — Evaluation Engine · standalone application.

Runs this module ALONE on its reserved port, for focused development without
the other 18 in the way:

    uvicorn backend_M13_Evaluation_Engine.app:app --reload --port 8113

The same router is also mounted into the gateway on :8000. Identical behaviour
either way. Ports: PORTS.txt.

**Rubrics load at startup, and a bad one fails the boot.** That is deliberate:
a rubric set that is silently one rubric short scores some rounds and not
others, and the missing one is discovered by a student. Failing loudly on a
machine is the cheap version of that discovery.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from ai_core.db import create_all, engine
from ai_core.modules_meta import ModuleStatus, module_status
from ai_core.schema_repair import ensure_schema
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import adapters, rubrics
from . import models as _models  # noqa: F401 - registers tables
from .dependencies import deps
from .keys import load_keys
from .router import router

log = logging.getLogger("uvicorn.error")


def _concept_domains() -> str:
    """M04's ontology, for the one question `emit.py` cannot answer itself:
    which concepts are communication rather than technical (AC-13.18).

    Without it no communication observation is written — which is the honest
    outcome, and better than the mint-an-id fallback it replaced, which had
    M04 reject every batch as "unknown concept" and take the turn's technical
    observation with it.
    """
    dep = deps().get("M04")
    if dep is None or not dep.base_url:
        return "none (no M04 base_url configured — no communication observations)"
    adapters.set_concept_domains(adapters.ConceptDomains(base_url=dep.base_url))
    return f"M04 at {dep.base_url}"


def _question_source() -> str:
    """M05 if `module.json` (or `M05_BASE_URL`) names one, fixtures otherwise.

    Wired at startup rather than per request so the choice is logged once and
    visible in one place. `LiveQuestions` keeps the fixture bank behind it, so
    this is additive: fixture ids and `question_label` resolve either way, and
    M05 being down narrows what can be scored rather than breaking it.
    """
    dep = deps().get("M05")
    if dep is None or not dep.base_url:
        return "fixtures (no M05 base_url configured)"
    adapters.set_questions(adapters.LiveQuestions(base_url=dep.base_url))
    return f"M05 at {dep.base_url}, fixtures behind it"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_keys()
    # create_all() makes missing TABLES and ignores existing ones, so a model
    # that gained a field leaves an older dev.db one column short and the next
    # query 500s. ensure_schema() adds those columns, additively.
    create_all()
    for change in ensure_schema(engine):
        log.info("schema: added missing column %s", change)
    loaded = rubrics.load_all()
    log.info(
        "M13 ready — rubrics: %s · questions: %s · ontology: %s",
        ", ".join(sorted(loaded)) or "none",
        _question_source(),
        _concept_domains(),
    )
    yield


app = FastAPI(title="M13 — Evaluation Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "module": "M13",
        "rubric_set_version": rubrics.rubric_set_version(),
        # No calibration is fitted in this slice, and saying so is the point:
        # §6.7's gate is closed, so no dimension displays a number yet.
        "calibration_version": "none",
    }


@app.get("/status", response_model=ModuleStatus, tags=["meta"])
def status() -> ModuleStatus:
    return module_status("M13")

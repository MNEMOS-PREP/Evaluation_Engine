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

from . import models as _models  # noqa: F401 - registers tables
from . import rubrics
from .keys import load_keys
from .router import router

log = logging.getLogger("uvicorn.error")


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
    log.info("M13 ready — rubrics: %s", ", ".join(sorted(loaded)) or "none")
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

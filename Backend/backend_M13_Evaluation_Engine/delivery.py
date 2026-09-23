"""The worker `emit.py` promised — spec §6.4 step 8, §6.11.

`emit.py` said *"a row is written in the same transaction as the evaluation,
and a worker drains it."* Until 2026-09-23 there was no worker: only
`POST /v1/outbox/drain`, which nothing called. The platform's core loop — a
question from M05, answered in M06, scored here, moving M04's skill graph —
closed for the first time on 2026-09-20 only because somebody drained this
outbox by hand. A student whose mastery moves only when an operator remembers
to press a button has a mastery map that is wrong by default.

The mechanism is `ai_core.outbox`, shared with every module that owes another
module something. This file declares only what M13 owes, and to whom:

    m04.observations   one POST per candidate, a LIST in one transaction —
                       M04's endpoint takes it that way and its 60 ms budget
                       is per call. Authenticated with `M04_SERVICE_SECRET`.
    m02.coverage       one POST per turn, forwarding the student's identity
                       exactly as M06 does when it writes the same ledger.

**Order does not matter between them, on purpose.** M02 accepts a score for a
turn whose `asked` row has not reached it yet (it parks the score and applies
it when the row lands), so neither this worker nor M06's has to wait for the
other. Ordering between two modules' queues is a coordination problem; making
the receiver commutative removes it.

**M19 is not a channel yet.** Its ledger entries are fully derivable from the
stored evaluation (`emit.ledger_entries`), so when M19 ships it gets a channel
here and a backfill, rather than a queue filling up today for a module that
does not exist.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from functools import lru_cache

from ai_core.db import engine
from ai_core.guard import identity_headers
from ai_core.outbox import Channel, Outcome, Sweeper, post_json
from sqlmodel import Session

from . import emit as emit_module
from .models import CoverageOutbox, ObservationOutbox

#: Seconds between sweeps. The sweep is the safety net: a fresh row goes out
#: when the evaluation that wrote it calls `kick()`. `0` turns it off, which is
#: what a demo showing the queue fill up wants.
SWEEP_S = float(os.getenv("M13_OUTBOX_SWEEP_S", "30"))

#: M04 answers in tens of milliseconds; anything near this is an outage.
SEND_TIMEOUT_S = 10.0

#: The legacy sender shape `store.drain(sender=...)` has always taken:
#: `(candidate_id, observations) -> (ok, detail)`.
LegacySender = Callable[[uuid.UUID, list[dict]], tuple[bool, str]]


def _observations(rows: list[ObservationOutbox]) -> Outcome:
    candidate_id = rows[0].candidate_id
    return post_json(
        emit_module.observations_url(candidate_id),
        {"observations": [dict(r.payload) for r in rows]},
        headers=emit_module.service_headers(),
        timeout=SEND_TIMEOUT_S,
    )


def _coverage(rows: list[CoverageOutbox]) -> Outcome:
    (row,) = rows  # one turn per send; see `coverage_channel`
    url = emit_module.coverage_url(row.session_id, row.candidate_id, row.turn_id)
    if url is None:
        # M02 was configured when this row was written and is not now. Nothing
        # to deliver to is not a failure of the row — and not a reason to keep
        # it owed against a module this deployment has chosen not to run.
        return Outcome.void("no M02 configured")
    return post_json(
        url,
        dict(row.payload),
        headers=identity_headers(row.candidate_id),
        timeout=SEND_TIMEOUT_S,
    )


def from_legacy(sender: LegacySender) -> Callable[[list[ObservationOutbox]], Outcome]:
    """Adapt `(ok, detail)` senders — the suite's fakes — to an `Outcome`.

    The reading is the one `store.drain` always applied: a 4xx other than 429
    will not become a 2xx on a retry; anything else might.
    """

    def send(rows: list[ObservationOutbox]) -> Outcome:
        ok, detail = sender(rows[0].candidate_id, [dict(r.payload) for r in rows])
        if ok:
            return Outcome.sent(detail)
        if detail.startswith("http_4") and not detail.startswith("http_429"):
            return Outcome.reject(detail)
        if detail.startswith("http_"):
            return Outcome.retry(detail)
        return Outcome.unreachable(detail)

    return send


def observation_channel(
    send: Callable[[list[ObservationOutbox]], Outcome] | None = None,
) -> Channel[ObservationOutbox]:
    return Channel(
        name="m04.observations",
        model=ObservationOutbox,
        send=send or _observations,
        batch_key=lambda row: row.candidate_id,
    )


def coverage_channel(
    send: Callable[[list[CoverageOutbox]], Outcome] | None = None,
) -> Channel[CoverageOutbox]:
    return Channel(name="m02.coverage", model=CoverageOutbox, send=send or _coverage)


def channels() -> list[Channel]:
    """Resolved per sweep, so a changed base URL is used without a restart."""
    return [observation_channel(), coverage_channel()]


def _session() -> Session:
    return Session(engine)


@lru_cache(maxsize=1)
def sweeper() -> Sweeper:
    return Sweeper("M13", _session, channels, interval_s=SWEEP_S)


def kick() -> None:
    """Deliver now. Called by the route that just wrote rows."""
    sweeper().kick()


__all__ = [
    "SWEEP_S",
    "channels",
    "coverage_channel",
    "from_legacy",
    "kick",
    "observation_channel",
    "sweeper",
]

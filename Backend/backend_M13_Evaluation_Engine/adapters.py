"""The upstream seam — spec §6.11.

M13 is Phase 1. Its upstreams are M5 (question packages) and M12 (delivery):
M5 is Phase 1–2 and M12 is Phase 3, so for most of this module's life neither
exists. Every module in this platform clones, installs and runs on its own,
and M13 is no exception — so question packages and delivery vectors enter
through an adapter, and the fixture implementation is the default.

The fixture bank is not a toy. It is the same file the regression suite reads
(§6.10): frozen `(question, answer, expected band)` cases with human-set
bands. Making it the M5 stand-in costs nothing and means the offline path and
the CI path exercise the same code.

Rule 2 applies to services as it does to students: a missing upstream narrows
the SCOPE of what we produce, never the quality, and never silently. No M5
means grounded items are unavailable and `item` is None — so the observation
M04 receives is not θ-eligible, which M04 §6.3 already handles. No M12 means
the delivery section is omitted with a reason, not zeroed.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5

from .contracts import DeliveryAssessment
from .projection import KeyPoint

log = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).parent / "fixtures"

#: Identifies this module to M05. Deliberately local rather than
#: `ai_core.models.USER_AGENT`: that landed in Platform_Core v0.8.0 and this
#: module is pinned to v0.6.0, and the header only matters for the provider
#: behind Cloudflare -- M05 is our own service on the same machine. Bumping the
#: pin is the identity rollout's job, not this seam's.
USER_AGENT = "AI-Interviewer-M13/1.0 (+https://github.com/MNEMOS-PREP)"

#: Stable ids for fixture questions, so a case has the same id everywhere.
FIXTURE_NAMESPACE = UUID("6f9c0b1e-9d2a-5c7b-8e3f-1a2b3c4d5e6f")


@dataclass
class ItemParams:
    """M04 §5.2's shape — the item AS ADMINISTERED, copied not referenced.

    None of it is available without M5, which is exactly why `theta_eligible`
    is derived rather than assumed: an observation with no item updates counts
    and evidence but must not move θ.
    """

    question_id: UUID
    irt_model: str = "grm"
    a: float = 1.0
    b: float | list[float] = 0.0
    params_source: str = "prior"
    bank_version: str = "fixtures"


@dataclass
class QuestionPackage:
    """What M5 hands over. An item without these is not usable for scoring."""

    question_id: UUID
    stem: str
    reference_answer: str
    key_points: list[KeyPoint] = field(default_factory=list)
    round_type: str = "dsa_verbal"
    concepts: dict[str, float] = field(default_factory=dict)
    item: ItemParams | None = None
    label: str = ""

    @property
    def theta_eligible(self) -> bool:
        return self.item is not None


@dataclass
class RegressionCase:
    """One frozen `(question, answer, expected band)` case — §6.10.

    `band_source` is on the record because the band's provenance is the whole
    point: a band snapshotted from a model's own output measures
    self-consistency and defends today's bias (Trap 9), while a band from
    adjudicated human consensus measures agreement with humans. The suite is
    only worth running if you can tell which one you have.
    """

    label: str
    question_label: str
    answer_text: str
    expected_band: tuple[int, int]
    band_source: str = "hand_set_from_anchors"
    note: str = ""

    def contains(self, score: float) -> bool:
        low, high = self.expected_band
        return low <= score <= high


class QuestionSource(Protocol):
    #: `round_type` is how the item was ADMINISTERED, and M05 requires it to
    #: build a package: an item eligible in two round types has two packages,
    #: and which one was asked is a fact about the turn rather than about the
    #: item (M05's own docstring on `/questions/{id}/package`). Every caller in
    #: this module knows it — the turn, the request, or the stored row — so it
    #: travels with the lookup.
    def get(self, question_id: UUID, round_type: str | None = None) -> QuestionPackage | None: ...
    def all(self) -> list[QuestionPackage]: ...


class DeliverySource(Protocol):
    def for_turn(self, turn_id: UUID) -> DeliveryAssessment | None: ...


# ─────────────────────────────────────────────────────────────────────────
#  Fixtures — the default, and the one CI uses
# ─────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_fixtures() -> tuple[dict[UUID, QuestionPackage], list[RegressionCase]]:
    packages: dict[UUID, QuestionPackage] = {}
    cases: list[RegressionCase] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in raw.get("cases", []):
            question_id = uuid5(FIXTURE_NAMESPACE, entry["label"])
            packages[question_id] = QuestionPackage(
                question_id=question_id,
                stem=entry["stem"],
                reference_answer=entry["reference_answer"],
                key_points=[KeyPoint(**kp) for kp in entry.get("key_points", [])],
                round_type=entry.get("round_type", "dsa_verbal"),
                concepts=entry.get("concepts", {}),
                item=None,  # fixtures are not calibrated items; never θ-eligible
                label=entry["label"],
            )
        for entry in raw.get("answers", []):
            band = entry["expected_band"]
            cases.append(
                RegressionCase(
                    label=entry["label"],
                    question_label=entry["question"],
                    answer_text=entry["text"],
                    expected_band=(int(band[0]), int(band[1])),
                    band_source=entry.get("band_source", "hand_set_from_anchors"),
                    note=entry.get("note", ""),
                )
            )
    log.info("loaded %d fixture question(s), %d regression case(s)", len(packages), len(cases))
    return packages, cases


@dataclass
class FixtureQuestions:
    name: str = "fixtures"

    def get(  # noqa: ARG002 - the fixture bank has one package per id
        self, question_id: UUID, round_type: str | None = None
    ) -> QuestionPackage | None:
        return _load_fixtures()[0].get(question_id)

    def by_label(self, label: str) -> QuestionPackage | None:
        return _load_fixtures()[0].get(uuid5(FIXTURE_NAMESPACE, label))

    def all(self) -> list[QuestionPackage]:
        return list(_load_fixtures()[0].values())


def regression_cases() -> list[RegressionCase]:
    """The frozen suite (§6.10). Also the adversarial cases from §12."""
    return list(_load_fixtures()[1])


# -------------------------------------------------------------------------
#  M04's ontology: which concepts are communication
# -------------------------------------------------------------------------


@dataclass
class ConceptDomains:
    """Which concepts belong to M04's `communication` domain, asked of M04.

    `emit.py` has to separate communication concepts from technical ones —
    that separation is AC-13.18, the rule that stops "spoke well" becoming
    "knows hashing". It used to test `cid.startswith("concept:communication")`,
    which matched none of M04's real ids (`concept:thinking_aloud`,
    `concept:summarising_concisely`, ...) and so fell through to a minted
    `concept:communication` that exists in no ontology. M04 rejected the batch
    as "unknown concept" and the turn's technical observation went down with
    it, so a fully scored interview moved nothing at all.

    A copied list here would be wrong the first time M04 adds a concept. M04
    owns the ontology and publishes it on a public route, so this asks, once,
    and caches until the ontology version changes.

    **When M04 cannot be reached, this is empty and no communication
    observation is written.** That is Rule 2: a missing upstream narrows what
    is claimed. It never invents an id to hang a score on.
    """

    base_url: str
    timeout_s: float = 3.0
    _cache: dict[str, frozenset[str]] = field(default_factory=dict)

    def communication(self) -> frozenset[str]:
        cached = self._cache.get("communication")
        if cached is not None:
            return cached
        rows = self._fetch()
        if rows is None:
            return frozenset()
        found = frozenset(
            str(row["id"]) for row in rows if row.get("domain") == "communication"
        )
        self._cache["communication"] = found
        log.info("M13: %d communication concepts from M04", len(found))
        return found

    def _fetch(self) -> list[dict] | None:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/concepts",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - an upstream that fails degrades
            log.info("M13: M04 ontology unreachable (%s)", type(exc).__name__)
            return None
        return body if isinstance(body, list) else body.get("concepts") or []


class NoConceptDomains:
    """No M04 configured. Communication scores are recorded on the evaluation
    and no observation is emitted for them — which is what M06's report says
    too when consent or an upstream is missing."""

    def communication(self) -> frozenset[str]:
        return frozenset()


# -------------------------------------------------------------------------
#  M05, live
# -------------------------------------------------------------------------


@dataclass
class LiveQuestions:
    """M05 over HTTP, with the fixture bank behind it.

    Until this existed `get_questions()` was ALWAYS the fixture bank, so
    `POST /v1/evaluations` answered 404 for every real M05 question id and
    nothing from the live bank could be scored by anybody. That is the Phase-1
    exit gate rather than a convenience: M06 selects a real item, and the turn
    it hands over has to be scoreable.

    **M05 builds the package, not this file.** It already serves
    `GET /v1/questions/{id}/package?round_type=` for exactly this, including
    the `item` parameters that decide whether the resulting observation may
    move an ability estimate. Rebuilding that from `/questions/{id}` here would
    put a second implementation of theta-eligibility in the module that must
    not own it.

    **The fixture bank stays behind it.** The regression suite, the adversarial
    cases and `question_label` all address fixture ids, and an M05 that is up
    must not make them unresolvable. So a miss falls through rather than
    failing -- which is also Rule 2: M05 down narrows what can be scored to the
    committed bank, and `/v1/deps` already says so in a sentence.
    """

    base_url: str
    fallback: QuestionSource = field(default_factory=FixtureQuestions)
    timeout_s: float = 3.0
    name: str = "m05"

    def get(self, question_id: UUID, round_type: str | None = None) -> QuestionPackage | None:
        package = self._fetch(question_id, round_type)
        if package is not None:
            return package
        return self.fallback.get(question_id, round_type)

    def by_label(self, label: str) -> QuestionPackage | None:
        """Fixture-only: labels are this repo's names for its own cases."""
        by_label = getattr(self.fallback, "by_label", None)
        return by_label(label) if by_label else None

    def all(self) -> list[QuestionPackage]:
        """The committed bank. M05 has no "every item" route, and a scoring
        engine has no business enumerating somebody else's bank."""
        return self.fallback.all()

    def _fetch(self, question_id: UUID, round_type: str | None) -> QuestionPackage | None:
        if round_type is None:
            # The item knows which round type it is scored under; ask it, then
            # ask for that package. Two calls, and only when the caller could
            # not say -- every caller in this module can.
            item = self._json(f"/v1/questions/{question_id}")
            if item is None:
                return None
            round_type = item.get("rubric_round_type") or (item.get("round_types") or [None])[0]
            if round_type is None:
                return None
        query = urllib.parse.urlencode({"round_type": round_type})
        raw = self._json(f"/v1/questions/{question_id}/package?{query}")
        return self._package(raw) if raw else None

    def _json(self, path: str) -> dict | None:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            # 404 (not M05's item) and 422 (not eligible in this round type)
            # are answers, not outages: fall through to the fixture bank.
            if exc.code not in (404, 422):
                log.info("M13: M05 %s -> HTTP %s", path, exc.code)
            return None
        except Exception as exc:  # noqa: BLE001 - an upstream that fails degrades
            log.info("M13: M05 %s unreachable (%s)", path, type(exc).__name__)
            return None

    @staticmethod
    def _package(raw: dict) -> QuestionPackage | None:
        try:
            item = raw.get("item")
            return QuestionPackage(
                question_id=UUID(str(raw["question_id"])),
                stem=raw["stem"],
                reference_answer=raw.get("reference_answer", ""),
                key_points=[
                    KeyPoint(
                        id=str(kp["id"]),
                        statement=kp["statement"],
                        weight=float(kp.get("weight", 1.0)),
                        required=bool(kp.get("required", False)),
                    )
                    for kp in raw.get("key_points", [])
                ],
                round_type=raw["round_type"],
                concepts={str(k): float(v) for k, v in (raw.get("concepts") or {}).items()},
                # Present only for a theta-eligible item: M05 sends None
                # otherwise, and `theta_eligible` is derived from exactly that.
                item=(
                    ItemParams(
                        question_id=UUID(str(item.get("question_id", raw["question_id"]))),
                        irt_model=str(item.get("irt_model", "grm")),
                        a=float(item.get("a", 1.0)),
                        b=item.get("b", 0.0),
                        params_source=str(item.get("params_source", "prior")),
                        bank_version=str(item.get("bank_version", "m05")),
                    )
                    if isinstance(item, dict)
                    else None
                ),
                label=str(raw.get("label", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("M13: M05 package was unusable (%s)", exc)
            return None


@dataclass
class NoDelivery:
    """M12 is Phase 3. Its absence omits a section; it never scores a zero."""

    name: str = "absent"

    def for_turn(self, turn_id: UUID) -> DeliveryAssessment | None:  # noqa: ARG002
        return None


_questions: QuestionSource = FixtureQuestions()
_delivery: DeliverySource = NoDelivery()


def get_questions() -> QuestionSource:
    return _questions


def set_questions(source: QuestionSource | None) -> None:
    global _questions
    _questions = source or FixtureQuestions()


_concept_domains: object = NoConceptDomains()


def get_concept_domains():
    return _concept_domains


def set_concept_domains(source) -> None:
    global _concept_domains
    _concept_domains = source or NoConceptDomains()


def get_delivery() -> DeliverySource:
    return _delivery


def set_delivery(source: DeliverySource | None) -> None:
    global _delivery
    _delivery = source or NoDelivery()


def reload() -> None:
    _load_fixtures.cache_clear()


__all__ = [
    "FixtureQuestions",
    "LiveQuestions",
    "ItemParams",
    "NoDelivery",
    "QuestionPackage",
    "RegressionCase",
    "get_delivery",
    "get_questions",
    "regression_cases",
    "reload",
    "set_delivery",
    "set_questions",
]

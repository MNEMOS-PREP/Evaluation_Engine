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
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5

from .contracts import DeliveryAssessment
from .projection import KeyPoint

log = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).parent / "fixtures"

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
    def get(self, question_id: UUID) -> QuestionPackage | None: ...
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

    def get(self, question_id: UUID) -> QuestionPackage | None:
        return _load_fixtures()[0].get(question_id)

    def by_label(self, label: str) -> QuestionPackage | None:
        return _load_fixtures()[0].get(uuid5(FIXTURE_NAMESPACE, label))

    def all(self) -> list[QuestionPackage]:
        return list(_load_fixtures()[0].values())


def regression_cases() -> list[RegressionCase]:
    """The frozen suite (§6.10). Also the adversarial cases from §12."""
    return list(_load_fixtures()[1])


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


def get_delivery() -> DeliverySource:
    return _delivery


def set_delivery(source: DeliverySource | None) -> None:
    global _delivery
    _delivery = source or NoDelivery()


def reload() -> None:
    _load_fixtures.cache_clear()


__all__ = [
    "FixtureQuestions",
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

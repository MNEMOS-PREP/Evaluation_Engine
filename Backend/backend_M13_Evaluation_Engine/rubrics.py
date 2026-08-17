"""Rubric loading — spec §6.1.

A rubric is a versioned, typed object, never a paragraph in a prompt. Loading
is where that becomes true: every rule §6.1 states is checked here, at load,
so a bad rubric fails on startup with a sentence naming the problem rather
than at scoring time with a number nobody can explain.

Four gates, all of them cheap and all of them things that have gone wrong in
real scoring systems:

* **Every level has a behavioural anchor.** A dimension without one is prose,
  which is Trap 1.
* **Exactly one dimension is concept-bearing.** Zero or two, and whoever wires
  M04 will average the dimensions — which silently folds communication into
  technical mastery (FR-13.22, AC-13.18).
* **Hint credit never increases with help.** A table where level 3 credits
  more than level 1 is a typo that would quietly reward taking hints.
* **`applies_when` is typed.** An unknown field fails here rather than
  producing a dimension that silently never applies.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from ai_core.timeutil import utcnow

from .contracts import AppliesWhen, Disqualifier, Rubric, RubricDimension

log = logging.getLogger(__name__)

RUBRIC_DIR = Path(__file__).parent / "rubrics"

#: Deterministic ids, so a rubric has the same id on every machine and a
#: version stamp means the same thing across two developers' databases.
RUBRIC_NAMESPACE = uuid5(NAMESPACE_URL, "https://mnemos.prep/m13/rubric")


class RubricError(ValueError):
    """A rubric that cannot be trusted to score with."""


def rubric_id_for(round_type: str, version: str) -> UUID:
    return uuid5(RUBRIC_NAMESPACE, f"{round_type}@{version}")


def parse_rubric(raw: dict, *, source: str = "<dict>") -> Rubric:
    """Turn a YAML document into a validated `Rubric`, or explain why not."""
    try:
        round_type = raw["round_type"]
        version = str(raw["version"])
    except KeyError as exc:  # pragma: no cover - trivial
        raise RubricError(f"{source}: missing required key {exc}") from exc

    dimensions: list[RubricDimension] = []
    for entry in raw.get("dimensions", []):
        applies = entry.get("applies_when")
        try:
            dimensions.append(
                RubricDimension(
                    key=entry["key"],
                    name=entry["name"],
                    description=entry.get("description", "").strip(),
                    # YAML gives int keys for `0:` but str keys for `"0":`.
                    anchors={int(k): str(v).strip() for k, v in entry["anchors"].items()},
                    weight=float(entry.get("weight", 1.0)),
                    evidence_required=bool(entry.get("evidence_required", True)),
                    applies_when=AppliesWhen(**applies) if applies else None,
                    concept_bearing=bool(entry.get("concept_bearing", False)),
                    pairwise=bool(entry.get("pairwise", False)),
                    concept_domain=entry.get("concept_domain", "technical"),
                )
            )
        except Exception as exc:
            raise RubricError(f"{source}: dimension '{entry.get('key', '?')}': {exc}") from exc

    disqualifiers = [
        Disqualifier(
            key=d["key"],
            description=d.get("description", ""),
            feeds=d.get("feeds", "both"),
        )
        for d in raw.get("disqualifiers", [])
    ]

    hint_penalty = {int(k): float(v) for k, v in (raw.get("hint_penalty") or {}).items()}

    try:
        return Rubric(
            id=rubric_id_for(round_type, version),
            version=version,
            round_type=round_type,
            dimensions=dimensions,
            disqualifiers=disqualifiers,
            hint_penalty=hint_penalty,
            created_at=_parse_created(raw.get("created_at")),
        )
    except Exception as exc:
        raise RubricError(f"{source}: {exc}") from exc


def _parse_created(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return utcnow()


def load_rubric_file(path: Path) -> Rubric:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RubricError(f"{path.name}: expected a mapping at the top level")
    return parse_rubric(raw, source=path.name)


@lru_cache(maxsize=1)
def load_all(directory: str | None = None) -> dict[str, Rubric]:
    """Every rubric on disk, keyed by round type. Cached; call `reload()` to reset.

    A single bad file fails the whole load rather than being skipped: a rubric
    set that is silently one rubric short scores some rounds and not others,
    and the missing one is discovered by a student.
    """
    folder = Path(directory) if directory else RUBRIC_DIR
    rubrics: dict[str, Rubric] = {}
    for path in sorted(folder.glob("*.yaml")):
        rubric = load_rubric_file(path)
        if rubric.round_type in rubrics:
            raise RubricError(
                f"{path.name}: duplicate round_type '{rubric.round_type}' "
                f"(already loaded from another file)"
            )
        rubrics[rubric.round_type] = rubric
    log.info("loaded %d rubric(s): %s", len(rubrics), ", ".join(sorted(rubrics)))
    return rubrics


def reload() -> None:
    load_all.cache_clear()


def get_rubric(round_type: str) -> Rubric:
    rubrics = load_all()
    if round_type not in rubrics:
        raise RubricError(
            f"no rubric for round type '{round_type}'. "
            f"Loaded: {', '.join(sorted(rubrics)) or 'none'}"
        )
    return rubrics[round_type]


def rubric_set_version() -> str:
    """A single string identifying the whole loaded set, for `/health`."""
    rubrics = load_all()
    if not rubrics:
        return "empty"
    return "+".join(f"{rt}@{r.version}" for rt, r in sorted(rubrics.items()))


__all__ = [
    "RubricError",
    "get_rubric",
    "load_all",
    "load_rubric_file",
    "parse_rubric",
    "reload",
    "rubric_set_version",
]

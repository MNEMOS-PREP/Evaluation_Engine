"""Upstream probing — spec §6.11, `module.json`.

Platform Rule 2, applied to services rather than students: **a missing
dependency narrows the SCOPE of what we produce, never the quality, and never
silently.** For M13 specifically that means:

* **M5 absent** — fixture questions, `item = None`, so the observation M04
  eventually receives is not θ-eligible. Scoring is unaffected.
* **M12 absent** — the delivery section is omitted with a reason. It is never
  zeroed; a student with no camera has not performed badly on presence, they
  have not been measured (EC-13.14).
* **M4 absent** — observations queue and replay. **The student's evaluation
  still completes**, because a downstream outage must never cost a student
  their score.

M13 declares no `required: true` dependency for exactly that reason: marking
one required turns someone else's outage into ours.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ai_core.dependencies import DependencyRegistry

MANIFEST = Path(__file__).resolve().parents[2] / "module.json"


@lru_cache(maxsize=1)
def deps() -> DependencyRegistry:
    return DependencyRegistry.from_manifest(MANIFEST)


def reload() -> None:
    deps.cache_clear()


__all__ = ["MANIFEST", "deps", "reload"]

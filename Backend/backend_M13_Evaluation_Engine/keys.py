"""Credential loading.

Two files, and the split between them is the point:

    required_keys.txt   COMMITTED. Every key this module can use, with dummy
                        values and a sentence saying what each one buys you.
                        Clone the repo, copy it to keys.txt, fill it in.
    keys.txt            NEVER COMMITTED. The real values. Gitignored.

Values already present in the environment win, so CI and a deployment can set
real environment variables without a file, and a developer can override one
key for one shell without editing anything.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

#: Searched in order, from the Backend directory upwards to the repo root.
KEY_FILES = ("keys.txt", ".env")


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve()
    roots = [here.parents[1], here.parents[2]]  # Backend/, repo root
    return [root / name for root in roots for name in KEY_FILES]


def load_keys(*, override: bool = False) -> list[str]:
    """Read keys.txt / .env into the environment. Returns the names loaded.

    Deliberately not python-dotenv: one function, no dependency, and the format
    is the one everybody already writes by hand.
    """
    loaded: list[str] = []
    for path in _candidate_paths():
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if not name or not value:
                continue
            if override or not os.getenv(name):
                os.environ[name] = value
                loaded.append(name)
    if loaded:
        # Names only. A log line that prints a key is a key in a log file.
        log.info("loaded %d credentials from %s", len(loaded), ", ".join(KEY_FILES))
    return loaded


def redact(key: str) -> str:
    """A key as it may appear in a log or an error message."""
    if not key:
        return "(none)"
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "(short)"


__all__ = ["KEY_FILES", "load_keys", "redact"]

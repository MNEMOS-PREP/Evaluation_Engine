"""Credential loading.

Two files, and the split between them is the point:

    required_keys.txt   COMMITTED. Every key this module can use, with dummy
                        values and a sentence saying what each one buys you.
                        Clone the repo, copy it to keys.txt, fill it in.
    keys.txt            NEVER COMMITTED. The real values. Gitignored.

Values already present in the environment win, so CI and a deployment can set
real environment variables without a file, and a developer can override one
key for one shell without editing anything.

**Load splitting.** Several providers hand out per-key rate limits rather than
per-account ones (Groq's free tier is per key, per minute), so a pool of keys
is a pool of quota. `KeyRing` round-robins across them, which turns two keys
into twice the throughput without a queue, a scheduler or a retry storm. It is
deliberately not smarter than that: a key that starts failing is a problem to
see in the logs, not to route around silently.
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
from dataclasses import dataclass, field
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


def keys_from_env(*names: str) -> list[str]:
    """Every key across the given variables, comma-split, de-duplicated.

    Accepts both the singular and plural forms of a variable (`GROQ_API_KEY`
    and `GROQ_API_KEYS`) because both exist in the wild and an operator should
    not have to remember which one this module reads.
    """
    out: list[str] = []
    for name in names:
        for part in os.getenv(name, "").split(","):
            key = part.strip()
            if key and key not in out:
                out.append(key)
    return out


@dataclass
class KeyRing:
    """Round-robin over a pool of API keys.

    Thread-safe because FastAPI runs sync endpoints in a threadpool and an
    ensemble fans out several evaluator calls at once: two callers taking the
    same key at the same moment would quietly halve the quota the pool exists
    to provide.
    """

    keys: list[str] = field(default_factory=list)
    _cycle: object | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._cycle = itertools.cycle(self.keys) if self.keys else None

    def __bool__(self) -> bool:
        return bool(self.keys)

    def __len__(self) -> int:
        return len(self.keys)

    def next(self) -> str:
        if self._cycle is None:
            raise RuntimeError("no API keys configured")
        with self._lock:
            return next(self._cycle)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, *names: str) -> KeyRing:
        return cls(keys=keys_from_env(*names))


def redact(key: str) -> str:
    """A key as it may appear in a log or an error message."""
    if not key:
        return "(none)"
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "(short)"


__all__ = ["KEY_FILES", "KeyRing", "keys_from_env", "load_keys", "redact"]

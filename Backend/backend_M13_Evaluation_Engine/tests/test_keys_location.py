"""Where M13 looks for its model keys.

On a fresh demo machine the only `keys.txt` is the one beside the repos —
the platform's one copy of each secret. Until 2026-10-03 this module read
only its own Backend/ and repo root, so on such a machine no answer is scored, while
M02 and M06, reading the shared file, had a model.
"""

from __future__ import annotations

from pathlib import Path

from backend_M13_Evaluation_Engine import keys


def test_the_shared_keys_file_beside_the_repos_is_read():
    beside_the_repos = Path(keys.__file__).resolve().parents[3]
    assert beside_the_repos / "keys.txt" in keys._candidate_paths()


def test_ai_keys_file_is_read_first(monkeypatch, tmp_path):
    mounted = tmp_path / "secrets" / "keys.txt"
    monkeypatch.setenv("AI_KEYS_FILE", str(mounted))
    assert keys._candidate_paths()[0] == mounted.resolve()

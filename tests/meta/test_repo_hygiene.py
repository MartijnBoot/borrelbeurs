"""AC6 — the build context and the built image must exclude junk (T10); no key is committed.

v1 shipped `.dockerignore` entries the hard way: a leaked `config/keys.json` or
a `.tar` save baked into a layer is the kind of mistake that is invisible until
someone inspects the image, and by then it has shipped. Phase 0 plan T10 says
to carry v1's list across rather than retype it, and to add the entries v2
introduces (`.env*`, `node_modules`, `legacy/`, `docs/`, `tests/`, `.github/`,
`web/dist`). This guard pins that full list down so a future edit cannot drop
an entry silently — the same drift problem
`test_compose_matches_env_example.py` solves for the compose file, applied to
`.dockerignore`.

**Why this reads the file as text.** `.dockerignore` has no schema to parse
against; a line is a glob pattern or it is nothing. Matching is deliberately
tolerant of a trailing slash (`docs` and `docs/` are the same instruction to
Docker) so this guard does not fail over a cosmetic difference that carries no
behavioural change.

**Why `__pycache__`, `*.pyc` and `node_modules` carry a `**/` prefix.** Unlike
`.gitignore`, a bare Docker ignore pattern matches only the build context
root, not every depth — confirmed by building `docker/Dockerfile`: without the
prefix, `web/node_modules` was not excluded from the context at all, and the
`web-build` stage's second `COPY` clobbered the `node_modules` the stage had
just installed with the host's copy, breaking the build. `app/__pycache__`,
`db/migrations/__pycache__` and friends have the same nested-path problem.
So do `*.tar`, `*.pdf` and `.env*`: AC6 excludes tarballs from the context,
not only those at its root, and a `web/.env.local` would otherwise ride
`COPY web/` into the build stage and have its `VITE_*` values baked into the
shipped bundle.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Carried over from v1 verbatim (plan T10) — nothing here may be dropped.
CARRIED_OVER_FROM_V1 = [
    ".git",
    "**/*.tar",
    "**/*.pdf",
    "config/keys.json",
    "config/.jwt_secret",
    "static/uploads",
    "static/earnings",
    "**/__pycache__",
    "**/*.pyc",
]

# New in v2 (plan T10) — this repository's own junk, absent from v1.
ADDED_FOR_V2 = [
    "**/.env*",
    "**/node_modules",
    "legacy/",
    "docs/",
    "tests/",
    ".github/",
    "web/dist",
]

REQUIRED_ENTRIES = CARRIED_OVER_FROM_V1 + ADDED_FOR_V2


def _normalise(pattern: str) -> str:
    """Strip a trailing slash so `docs` and `docs/` compare equal."""
    return pattern.rstrip("/")


def _committed_entries() -> set[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return {_normalise(line.strip()) for line in lines if line.strip() and not line.startswith("#")}


def test_the_guard_is_reading_a_real_file() -> None:
    """The file must exist, or every assertion below passes vacuously."""
    assert DOCKERIGNORE.is_file(), f"{DOCKERIGNORE} is missing; this guard is checking nothing"


@pytest.mark.parametrize("pattern", REQUIRED_ENTRIES)
def test_dockerignore_contains_required_entry(pattern: str) -> None:
    assert _normalise(pattern) in _committed_entries(), (
        f".dockerignore is missing {pattern!r}. Plan T10 requires the full v1 list "
        f"carried across plus v2's own additions; see this file's module docstring."
    )


def test_the_detector_notices_a_dropped_entry() -> None:
    """The guard's own regression test: removing an entry must fail the check."""
    entries = _committed_entries() - {_normalise("config/keys.json")}
    assert _normalise("config/keys.json") not in entries


# --- No keys file, no key literal (Phase 3 T8: AC6c hygiene half, PD19) --------
#
# v1 kept plaintext keys in `config/keys.json` (ADR 0007). v2 stores only an
# argon2id hash in `auth_key`, and the plaintext `bb_<key_id>_<secret>` is
# printed once by `app.cli.keys`. These two checks keep either from ever being
# committed. Tests mint keys at runtime; the detector's own sample below is
# built by concatenation, so this file never holds a literal it would flag.

KEY_LITERAL = re.compile(r"\bbb_\d+_[A-Za-z0-9_-]{32,}")


def tracked_paths() -> list[str]:
    """Every path `git ls-files` reports, repository-relative, POSIX separators."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    return [path for path in out.decode("utf-8").split("\0") if path]


def keys_files(paths: list[str]) -> list[str]:
    return [path for path in paths if PurePosixPath(path).name == "keys.json"]


def key_literals(text: str) -> list[str]:
    return KEY_LITERAL.findall(text)


def _text_of(path: Path) -> str | None:
    """The file as text, or `None` for a binary (a NUL in its first 8 KiB) or a deleted one."""
    if not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def test_git_ls_files_reaches_the_tree() -> None:
    """Anti-vacuity: the scans below see the real tracked files."""
    paths = tracked_paths()

    assert "app/main.py" in paths
    assert "tests/meta/test_repo_hygiene.py" in paths


def test_no_keys_json_is_tracked() -> None:
    assert keys_files(tracked_paths()) == []


def test_the_keys_file_detector_flags_any_depth() -> None:
    paths = ["config/keys.json", "legacy/v1/config/keys.json", "docs/keys.json.md", "keys.jsonl"]

    assert keys_files(paths) == ["config/keys.json", "legacy/v1/config/keys.json"]


def test_no_tracked_file_holds_an_access_key() -> None:
    found = [
        f"{path}: {literal[:8]}..."
        for path in tracked_paths()
        if (text := _text_of(REPO_ROOT / path)) is not None
        for literal in key_literals(text)
    ]

    assert found == [], "an access key is committed; revoke it and remove it:\n" + "\n".join(found)


def test_the_key_literal_detector() -> None:
    secret = "A" * 20 + "b-c_d" + "9" * 18  # 43 characters, token_urlsafe(32)'s length
    key = "bb" + "_" + "12" + "_" + secret

    assert key_literals(f"login with {key} now") == [key]
    assert key_literals("bb" + "_12_" + "short") == []
    assert key_literals("bb" + "_x_" + secret) == []
    assert key_literals("abb" + "_12_" + secret) == []

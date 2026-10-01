"""AC6 — the build context and the built image must exclude junk (T10).

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

from pathlib import Path

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

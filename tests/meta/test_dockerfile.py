"""AC1 (Phase 8 T11): the Dockerfile's shape, read as text.

Every base image digest-pinned (the venue bundle must carry exactly the image that was
tested, ADR 0004), at least two stages (no toolchain in the runtime image), a numeric
non-root final user, and the `BUILD_SHA` build argument `/healthz` reports (AC6).
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "docker" / "Dockerfile"


def _instructions() -> list[tuple[str, str]]:
    """`(INSTRUCTION, arguments)` per line, comments and continuations folded."""
    joined = re.sub(r"\\\r?\n", " ", DOCKERFILE.read_text(encoding="utf-8"))
    out = []
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            keyword, _, rest = stripped.partition(" ")
            out.append((keyword.upper(), rest.strip()))
    return out


def _runtime() -> list[tuple[str, str]]:
    instructions = _instructions()
    last_from = max(i for i, (keyword, _) in enumerate(instructions) if keyword == "FROM")
    return instructions[last_from:]


def test_every_base_image_is_digest_pinned() -> None:
    froms = [rest for keyword, rest in _instructions() if keyword == "FROM"]

    assert froms
    assert all(re.search(r"@sha256:[0-9a-f]{64}\b", rest) for rest in froms), froms


def test_it_has_at_least_two_stages() -> None:
    assert sum(keyword == "FROM" for keyword, _ in _instructions()) >= 2


def test_the_final_user_is_numeric_and_not_root() -> None:
    users = [rest for keyword, rest in _runtime() if keyword == "USER"]

    assert users, "no USER: the image would run as root"
    assert users[-1].isdigit() and int(users[-1]) != 0, users[-1]


def test_the_build_sha_is_a_build_argument_of_the_runtime_stage() -> None:
    runtime = _runtime()

    assert ("ARG", "BUILD_SHA=unknown") in runtime
    assert any(keyword == "ENV" and "BUILD_SHA=$BUILD_SHA" in rest for keyword, rest in runtime)


def test_the_build_sha_comes_after_the_dependency_install() -> None:
    """An ARG is an env var of every later RUN: before `uv sync`, each commit would
    rebuild the dependency layer."""
    runtime = _runtime()
    install = next(i for i, (k, rest) in enumerate(runtime) if k == "RUN" and "uv sync" in rest)
    arg = next(i for i, (k, rest) in enumerate(runtime) if k == "ARG" and "BUILD_SHA" in rest)

    assert install < arg

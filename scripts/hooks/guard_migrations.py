"""`PreToolUse` hook: refuse to write to a superseded migration file.

way-of-working §5.6:893 -- "Configure a hook that blocks the agent from
writing to already-applied migration files." Phase 0 has no long-lived
database this hook could query for "applied", so it enforces the checkable
half of that rule instead: a revision that already has a successor is never
the one to edit -- add a new revision (the same rule
`db/migrations/versions/0001_baseline.py`'s own docstring states, and the one
`docs/way-of-working.md` names at that line). The newest revision is still
open; the day it gains a successor it stops being writable, without this file
changing.

**Deliberately stdlib only.** This runs as a subprocess on every `Write`,
`Edit` and `MultiEdit` call, so it must start in milliseconds and must not
assume this repository's own virtualenv is the one Python invoking it can
see -- the same reasoning that keeps `app/core/config.py` boot-critical and
dependency-free. `alembic.script.ScriptDirectory` would answer "what is the
head?" more completely (branch labels, `depends_on`), but it requires an
installed Alembic; the graph this project actually has -- Phase 0 ships one
straight chain -- does not need it, and
`tests/meta/test_migration_scaffolding.py::test_the_migration_directory_has_exactly_one_head`
already guards the invariant this simplification relies on.

Protocol: one JSON object arrives on stdin, matching Claude Code's
`PreToolUse` hook contract. Exit 0 to allow (nothing need be printed); exit 2
and a message on stderr to block -- that message is what a blocked agent, and
a human reading the transcript, both see.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "db" / "migrations" / "versions"

# The tool names that can put new bytes on disk. `NotebookEdit` is
# future-proofing -- this repository has no notebooks -- rather than a case
# this hook has ever actually seen.
MUTATING_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

ALLOW = 0
BLOCK = 2


def _literal(node: ast.expr | None) -> str | None:
    """A string or `None` literal. Anything else (a name, a call) is not one."""
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, str)):
        return node.value
    return None


def parse_revision(path: Path) -> tuple[str, str | None] | None:
    """`(revision, down_revision)` for one migration file, read as source.

    Parsed, never imported -- Alembic's own `ScriptDirectory` executes each
    file, which this hook has no business doing to a file an agent is about
    to overwrite. Returns `None` for a file that declares no top-level
    `revision` (an `__init__.py`, a stray non-migration file, or a file that
    does not exist yet): such a file has no position in the chain and this
    hook has nothing to say about it.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None

    revision: str | None = None
    down_revision: str | None = None
    for statement in tree.body:
        # Alembic's own template annotates both `revision: str = ...` and
        # `down_revision: str | None = ...` (`script.py.mako:30-31`) -- that's
        # `ast.AnnAssign` (always exactly one target). `ast.Assign` (possibly
        # several targets) is read too, for a bare `down_revision = ...` such
        # as a hand-written or older-style migration might use.
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue

        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                revision = _literal(value)
            elif target.id == "down_revision":
                down_revision = _literal(value)

    if revision is None:
        return None
    return revision, down_revision


def load_chain(versions_dir: Path) -> dict[str, tuple[str | None, Path]]:
    """Every migration in `versions_dir`, keyed by its own revision id."""
    chain: dict[str, tuple[str | None, Path]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        parsed = parse_revision(path)
        if parsed is not None:
            revision, down_revision = parsed
            chain[revision] = (down_revision, path)
    return chain


def head_paths(versions_dir: Path) -> set[Path]:
    """The migration(s) nothing else in the chain names as its `down_revision`.

    Normally exactly one --
    `test_the_migration_directory_has_exactly_one_head` guards that
    invariant elsewhere. An unparseable or empty directory yields an empty
    set, which `decide` below reads as "nothing to protect".
    """
    chain = load_chain(versions_dir)
    parents = {down for down, _ in chain.values() if down is not None}
    return {path.resolve() for revision, (_, path) in chain.items() if revision not in parents}


def decide(file_path: Path, versions_dir: Path = VERSIONS_DIR) -> tuple[bool, str]:
    """Whether `file_path` may be written, and why.

    Allowed unconditionally: anything outside `versions_dir`; a file that
    does not exist yet (a brand-new revision is, by definition, not
    superseding anything); a file that is not shaped like a migration
    (`__init__.py`). Everything else is allowed only if it is a current head.
    """
    resolved = file_path.resolve()
    try:
        resolved.relative_to(versions_dir.resolve())
    except ValueError:
        return True, "outside db/migrations/versions/"

    if not resolved.exists():
        return True, "new file -- not yet part of the migration chain"

    if parse_revision(resolved) is None:
        return True, "not shaped like a migration file"

    heads = head_paths(versions_dir)
    if not heads:
        return True, "no parseable revisions found; nothing to compare against"

    if resolved in heads:
        return True, f"{resolved.name} is the newest revision"

    newest = ", ".join(sorted(path.name for path in heads))
    return False, (
        f"guard_migrations: refusing to write to {resolved.name} -- it is not the "
        f"newest revision in db/migrations/versions/ (newest: {newest}). Never edit "
        f"a migration that already has a successor; add a new one instead "
        f"(way-of-working.md 5.6:893)."
    )


def main(*, versions_dir: Path = VERSIONS_DIR) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        # Malformed input is this hook's failure, not the tool call's --
        # blocking every Write/Edit in the session over an unreadable payload
        # would cost far more than the one gap it would close. Fails open,
        # visibly.
        print(
            f"guard_migrations: could not parse hook payload ({error}); allowing", file=sys.stderr
        )
        return ALLOW

    if payload.get("tool_name") not in MUTATING_TOOLS:
        return ALLOW

    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path:
        return ALLOW

    allowed, message = decide(Path(file_path), versions_dir)
    if not allowed:
        print(message, file=sys.stderr)
        return BLOCK
    return ALLOW


if __name__ == "__main__":
    raise SystemExit(main())

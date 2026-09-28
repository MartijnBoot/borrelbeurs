"""T7's one promise: Phase 2's first migration has a parent to chain from.

The baseline revision is only half of that promise. The other half is that
`alembic revision` *works* — and it is the half that no other check touches,
because `upgrade` and `downgrade` never construct a new revision file. That
asymmetry already cost one gate: `timezone = UTC` in `db/alembic.ini` made
Alembic resolve a zone through `zoneinfo`, which on Windows finds nothing
unless `tzdata` is installed, so `revision` raised "Can't locate timezone: UTC"
*before writing any file* while a full up/down/up run stayed green.

So this generates a revision and asserts it hangs off the current head. It runs
against the real `db/alembic.ini` and the real `db/migrations/` — a copy of the
latter, in a temporary directory, so a passing test leaves no file behind and a
failing one cannot strand a second head in the repository.

No database is involved: `alembic revision` without `--autogenerate` never runs
`env.py`, and therefore never reads the environment.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import Script, ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "db" / "alembic.ini"
MIGRATIONS = REPO_ROOT / "db" / "migrations"


def _scratch_config(tmp_path: Path) -> Config:
    """The committed `alembic.ini`, aimed at a throwaway copy of the revisions.

    Every setting under test — `file_template`, `script.py.mako`, and the
    absence of `timezone` — comes from the real files. Only the directory new
    revisions land in is redirected.
    """
    scratch = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, scratch, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(scratch))
    return config


def _revise(config: Config, rev_id: str) -> Script:
    """`alembic revision --rev-id <id>`, as a single non-branching revision."""
    created = command.revision(config, message="scaffolding probe", rev_id=rev_id)
    assert isinstance(created, Script), f"expected one revision, got {created!r}"
    return created


def test_prepend_sys_path_resolves_to_the_repository_root() -> None:
    """env.py imports `app`, and `package = false` makes this the only route to it.

    Without `path_separator` Alembic splits the value on spaces, commas and
    colons, so on Windows `C:\\...\\db/..` became `['C', '/...']` -- right only
    by accident, and wrong outright for a checkout under a path with a space.
    """
    paths = Config(str(ALEMBIC_INI)).get_prepend_sys_paths_list()

    assert paths is not None
    assert [Path(p).resolve() for p in paths] == [REPO_ROOT]


def test_the_migration_directory_has_exactly_one_head(tmp_path: Path) -> None:
    """A single head, or "the parent" is not a well-defined thing to chain onto."""
    heads = ScriptDirectory.from_config(_scratch_config(tmp_path)).get_heads()

    assert len(heads) == 1, f"db/migrations has {len(heads)} heads: {heads}"


def test_a_new_revision_can_be_generated_and_chains_onto_the_head(tmp_path: Path) -> None:
    """The property T7 exists for (and the regression test for `timezone = UTC`).

    If this raises `CommandError: Can't locate timezone: ...`, someone has put a
    `timezone =` line back into `db/alembic.ini` on a machine with no tz
    database. Delete the line; `Create Date` is a docstring comment, not data.
    """
    config = _scratch_config(tmp_path)
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None, "db/migrations has no head; the baseline revision is missing"

    created = _revise(config, rev_id="9999")

    assert created.down_revision == head
    assert created.revision == "9999"
    assert Path(created.path).is_file()
    assert Path(created.path).parent == tmp_path / "migrations" / "versions"


def test_the_generated_revision_is_importable_python(tmp_path: Path) -> None:
    """The template renders source, not something that merely looks like it.

    `ScriptDirectory.get_revision` imports the file, so a template that emitted
    a stray `${...}` or an unquoted revision id fails here rather than in Phase
    2 at `upgrade`.
    """
    config = _scratch_config(tmp_path)
    _revise(config, rev_id="9999")

    revision = ScriptDirectory.from_config(config).get_revision("9999")

    assert revision.module.revision == "9999"
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)


def test_the_generated_revision_quotes_identifiers_the_way_ruff_format_does(
    tmp_path: Path,
) -> None:
    """P3 — `repr()` writes single quotes, and the gate's first step rewrites them.

    `scripts/check.sh` runs `ruff format --check` before anything else and stops
    on the first failure, so a revision that is unformatted the moment it is
    born red-lights the whole gate on a file nobody has edited.
    """
    created = _revise(_scratch_config(tmp_path), rev_id="9999")
    source = Path(created.path).read_text(encoding="utf-8")

    assert 'revision: str = "9999"' in source
    assert "'" not in source.split('"""', 2)[-1], "single-quoted literal outside the docstring"

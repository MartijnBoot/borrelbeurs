"""Phase 8 AC11: every migration after `0011` says what it does to the rollback floor.

SD3 lets an older image serve a newer schema when the newer schema's
`schema_compat.min_code_revision` is a revision the older image knows. That is only
true if every migration keeps the row honest, so each one after `0011` must declare,
at module level:

- `min_code_revision = "unchanged"` -- expand-only: older code still runs; or
- `min_code_revision = "<revision id>"` -- a contract: code older than that revision
  no longer runs. The id is the migration's own or an earlier one, and its
  `upgrade()` calls `set_min_code_revision` (`db/migrations/compat.py`) to store it.

`script.py.mako` writes `min_code_revision = ...`, which is neither, so a freshly
generated revision fails here until its author decides (PD2). Read by AST, as the
other migration guards do, so nothing here runs a migration.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "db" / "alembic.ini"
MIGRATIONS = REPO_ROOT / "db" / "migrations"
FLOOR = "0011"
UNCHANGED = "unchanged"
SETTER = "set_min_code_revision"


def _declared(tree: ast.Module) -> ast.expr | None:
    """The value of the module-level `min_code_revision` assignment, if any."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "min_code_revision"
            for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "min_code_revision"
        ):
            return node.value
    return None


def _upgrade_stores(tree: ast.Module, revision: str) -> bool:
    """`upgrade()` calls the setter with that id, literally or as `min_code_revision`."""
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "upgrade"):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name != SETTER:
                continue
            for arg in call.args:
                if isinstance(arg, ast.Constant) and arg.value == revision:
                    return True
                if isinstance(arg, ast.Name) and arg.id == "min_code_revision":
                    return True
    return False


def coverage_faults(migrations: Path) -> list[str]:
    """One line per migration after the floor that breaks the rule above."""
    script = ScriptDirectory(str(migrations))
    order = [entry.revision for entry in reversed(list(script.walk_revisions()))]
    assert FLOOR in order, f"{FLOOR} is not in the chain under {migrations}"
    faults = []
    for position, revision in enumerate(order):
        if position <= order.index(FLOOR):
            continue
        path = Path(script.get_revision(revision).path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        value = _declared(tree)
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            faults.append(f"{path.name}: min_code_revision must be {UNCHANGED!r} or a revision id")
            continue
        declared = value.value
        if declared == UNCHANGED:
            continue
        if declared not in order[: position + 1]:
            faults.append(
                f"{path.name}: min_code_revision {declared!r} is not this revision or an "
                "earlier one"
            )
        elif not _upgrade_stores(tree, declared):
            faults.append(f"{path.name}: upgrade() does not call {SETTER}(op, {declared!r})")
    return faults


def test_every_migration_after_the_floor_declares_min_code_revision() -> None:
    assert coverage_faults(MIGRATIONS) == []


# --- the guard bites (scratch copies; the repository is never touched) --------


def _scratch(tmp_path: Path) -> tuple[Path, Config]:
    scratch = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, scratch, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(scratch))
    return scratch, config


def _write(scratch: Path, revision: str, body: str) -> None:
    head = ScriptDirectory(str(scratch)).get_current_head()
    (scratch / "versions" / f"{revision}_probe.py").write_text(
        f'"""probe"""\n\nrevision = "{revision}"\ndown_revision = "{head}"\n'
        f"branch_labels = None\ndepends_on = None\n{body}",
        encoding="utf-8",
    )


UPGRADE_NOOP = "\n\ndef upgrade() -> None:\n    pass\n\n\ndef downgrade() -> None:\n    pass\n"


def test_a_freshly_generated_revision_fails_until_its_author_decides(tmp_path: Path) -> None:
    """AC11: the template's `...` is neither `"unchanged"` nor an id."""
    scratch, config = _scratch(tmp_path)
    command.revision(config, message="probe", rev_id="9999")

    (fault,) = coverage_faults(scratch)

    assert fault.startswith("9999_probe.py: min_code_revision must be")


def test_a_migration_with_no_declaration_fails(tmp_path: Path) -> None:
    scratch, _ = _scratch(tmp_path)
    _write(scratch, "9999", UPGRADE_NOOP)

    assert [f.split(":")[0] for f in coverage_faults(scratch)] == ["9999_probe.py"]


def test_unchanged_passes(tmp_path: Path) -> None:
    scratch, _ = _scratch(tmp_path)
    _write(scratch, "9999", 'min_code_revision = "unchanged"\n' + UPGRADE_NOOP)

    assert coverage_faults(scratch) == []


def test_a_contract_that_stores_its_id_passes(tmp_path: Path) -> None:
    scratch, _ = _scratch(tmp_path)
    _write(
        scratch,
        "9999",
        'min_code_revision = "9999"\n\n\ndef upgrade() -> None:\n'
        "    set_min_code_revision(op, min_code_revision)\n",
    )

    assert coverage_faults(scratch) == []


def test_a_contract_that_does_not_store_its_id_fails(tmp_path: Path) -> None:
    scratch, _ = _scratch(tmp_path)
    _write(scratch, "9999", 'min_code_revision = "9999"\n' + UPGRADE_NOOP)

    (fault,) = coverage_faults(scratch)

    assert SETTER in fault


def test_a_floor_naming_a_later_or_unknown_revision_fails(tmp_path: Path) -> None:
    scratch, _ = _scratch(tmp_path)
    _write(
        scratch,
        "9999",
        'min_code_revision = "elsewhere"\n\n\ndef upgrade() -> None:\n'
        '    set_min_code_revision(op, "elsewhere")\n',
    )

    (fault,) = coverage_faults(scratch)

    assert "is not this revision or an earlier one" in fault

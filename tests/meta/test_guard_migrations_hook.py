"""T13 -- the migration guard hook, unit-tested directly.

`scripts/hooks/guard_migrations.py` is wired into `.claude/settings.json` as
a `PreToolUse` hook, so the harness runs it on every `Write`/`Edit`/`MultiEdit`
call. That registration is config, not code, and is not exercised here. What
actually decides "block or allow" lives in the script and is tested here, the same way
`test_migration_scaffolding.py` tests Alembic's behaviour against real and
scratch copies of `db/migrations/`.

Two levels: `decide()` (and its helpers) directly, and `main()` end-to-end
through the real stdin/stdout/exit-code contract a hook subprocess is judged
by.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.hooks.guard_migrations import (
    ALLOW,
    BLOCK,
    REPO_ROOT,
    VERSIONS_DIR,
    decide,
    head_paths,
    load_chain,
    main,
    parse_revision,
)


def _write_revision(directory: Path, name: str, revision: str, down_revision: str | None) -> Path:
    """A minimal migration file carrying only the fields the guard reads — not shaped like
    Alembic's real template; see `_write_templated_revision` below for that shape."""
    down = "None" if down_revision is None else f'"{down_revision}"'
    path = directory / name
    path.write_text(
        f'"""probe revision"""\n\nrevision: str = "{revision}"\ndown_revision = {down}\n',
        encoding="utf-8",
    )
    return path


def _write_templated_revision(
    directory: Path, name: str, revision: str, down_revision: str | None
) -> Path:
    """A migration shaped exactly like `db/migrations/script.py.mako` renders it.

    `script.py.mako:30-31` annotates *both* assignments:
    `revision: str = ...` and `down_revision: str | None = ...` -- both
    `ast.AnnAssign`, not the bare `ast.Assign` `_write_revision` above uses for
    `down_revision`. This is the shape of every migration this repo generates
    after the baseline, and it is the shape that catches a parser which only
    reads `revision` out of an `AnnAssign` and silently drops an annotated
    `down_revision` (see the task report for the mutation this proves against).
    """
    down = "None" if down_revision is None else f'"{down_revision}"'
    path = directory / name
    path.write_text(
        f'"""probe revision"""\n\n'
        f'revision: str = "{revision}"\n'
        f"down_revision: str | None = {down}\n",
        encoding="utf-8",
    )
    return path


# --- parse_revision -----------------------------------------------------------


def test_parse_revision_reads_revision_and_down_revision(tmp_path: Path) -> None:
    path = _write_revision(tmp_path, "0002_next.py", "0002", "0001")

    assert parse_revision(path) == ("0002", "0001")


def test_parse_revision_reads_a_root_revision_with_no_parent(tmp_path: Path) -> None:
    path = _write_revision(tmp_path, "0001_baseline.py", "0001", None)

    assert parse_revision(path) == ("0001", None)


def test_parse_revision_returns_none_for_a_file_with_no_revision(tmp_path: Path) -> None:
    path = tmp_path / "__init__.py"
    path.write_text("", encoding="utf-8")

    assert parse_revision(path) is None


def test_parse_revision_returns_none_for_unparseable_python(tmp_path: Path) -> None:
    path = tmp_path / "0003_broken.py"
    path.write_text("revision = 'unterminated\n", encoding="utf-8")

    assert parse_revision(path) is None


def test_parse_revision_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    assert parse_revision(tmp_path / "does_not_exist.py") is None


def test_parse_revision_reads_an_annotated_down_revision(tmp_path: Path) -> None:
    """The shape every post-baseline migration actually has (`script.py.mako`
    annotates `down_revision` too, not just `revision`) -- not the real
    baseline, whose `down_revision` is `None` and so cannot distinguish a
    parser that reads an annotated `down_revision` from one that silently
    drops it."""
    path = _write_templated_revision(tmp_path, "0002_next.py", "0002", "0001")

    assert parse_revision(path) == ("0002", "0001")


def test_head_paths_with_templated_revisions_identifies_the_single_head(tmp_path: Path) -> None:
    """`head_paths` relies on `down_revision` being read correctly to link the
    chain; if an annotated `down_revision` were dropped, every file would look
    parentless and every file would look like a head."""
    _write_templated_revision(tmp_path, "0001_baseline.py", "0001", None)
    second = _write_templated_revision(tmp_path, "0002_next.py", "0002", "0001")

    assert head_paths(tmp_path) == {second.resolve()}


def test_parse_revision_reads_the_real_baseline_revision() -> None:
    """Anti-vacuity: the real file this hook exists to protect parses cleanly."""
    parsed = parse_revision(VERSIONS_DIR / "0001_baseline.py")

    assert parsed is not None
    revision, down_revision = parsed
    assert revision == "0001"
    assert down_revision is None


# --- load_chain / head_paths ---------------------------------------------------


def test_head_paths_identifies_the_single_head(tmp_path: Path) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    second = _write_revision(tmp_path, "0002_next.py", "0002", "0001")

    assert head_paths(tmp_path) == {second.resolve()}


def test_head_paths_on_an_empty_directory_is_empty(tmp_path: Path) -> None:
    assert head_paths(tmp_path) == set()


def test_load_chain_ignores_non_migration_files(tmp_path: Path) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    assert set(load_chain(tmp_path)) == {"0001"}


def test_head_paths_on_the_real_repository_is_the_one_baseline_file() -> None:
    """Anti-vacuity, against the real tree: today's only head is 0001_baseline.py.

    If this ever fails because a second revision landed, that is expected --
    update the assertion, it is not this guard that broke.
    """
    heads = head_paths(VERSIONS_DIR)

    assert heads == {(VERSIONS_DIR / "0001_baseline.py").resolve()}


# --- decide ---------------------------------------------------------------------


def test_decide_allows_the_newest_revision(tmp_path: Path) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    second = _write_revision(tmp_path, "0002_next.py", "0002", "0001")

    allowed, _ = decide(second, versions_dir=tmp_path)

    assert allowed is True


def test_decide_blocks_a_superseded_revision(tmp_path: Path) -> None:
    first = _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    _write_revision(tmp_path, "0002_next.py", "0002", "0001")

    allowed, message = decide(first, versions_dir=tmp_path)

    assert allowed is False
    assert "0001_baseline.py" in message
    assert "0002_next.py" in message


def test_decide_allows_the_only_revision_that_exists(tmp_path: Path) -> None:
    """One revision is trivially its own head -- nothing supersedes it yet."""
    only = _write_revision(tmp_path, "0001_baseline.py", "0001", None)

    allowed, _ = decide(only, versions_dir=tmp_path)

    assert allowed is True


def test_decide_allows_a_brand_new_file_that_does_not_exist_yet(tmp_path: Path) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)

    allowed, message = decide(tmp_path / "0002_not_written_yet.py", versions_dir=tmp_path)

    assert allowed is True
    assert "not yet part of the migration chain" in message


def test_decide_allows_paths_outside_the_versions_directory(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "notes.py"
    outside.parent.mkdir()
    outside.write_text("revision = '0001'\n", encoding="utf-8")

    allowed, message = decide(outside, versions_dir=tmp_path / "versions")

    assert allowed is True
    assert "outside" in message


def test_decide_allows_a_non_migration_file_inside_the_versions_directory(tmp_path: Path) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    init_file = tmp_path / "__init__.py"
    init_file.write_text("", encoding="utf-8")

    allowed, _ = decide(init_file, versions_dir=tmp_path)

    assert allowed is True


def test_decide_on_the_real_repository_allows_the_real_baseline_today() -> None:
    """The task's own verification, against the real tree as it stands: with
    exactly one revision on disk, 0001_baseline.py *is* the newest, so an edit
    to it is allowed -- the blocking case needs a second revision, exercised
    above and in the `main()` tests below with a scratch copy."""
    allowed, _ = decide(VERSIONS_DIR / "0001_baseline.py")

    assert allowed is True


# --- main(): the real stdin/stdout/exit-code contract --------------------------


def _run_main(
    payload: Mapping[str, object], *, versions_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return main(versions_dir=versions_dir)


def test_main_blocks_editing_a_superseded_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    _write_revision(tmp_path, "0002_next.py", "0002", "0001")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(first), "old_string": "a", "new_string": "b"},
    }

    exit_code = _run_main(payload, versions_dir=tmp_path, monkeypatch=monkeypatch)

    assert exit_code == BLOCK
    assert "0001_baseline.py" in capsys.readouterr().err


def test_main_allows_editing_the_newest_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    second = _write_revision(tmp_path, "0002_next.py", "0002", "0001")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(second), "old_string": "a", "new_string": "b"},
    }

    exit_code = _run_main(payload, versions_dir=tmp_path, monkeypatch=monkeypatch)

    assert exit_code == ALLOW
    assert capsys.readouterr().err == ""


def test_main_allows_write_of_a_brand_new_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "0002_new.py"),
            "content": 'revision = "0002"\ndown_revision = "0001"\n',
        },
    }

    assert _run_main(payload, versions_dir=tmp_path, monkeypatch=monkeypatch) == ALLOW


def test_main_ignores_non_mutating_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = _write_revision(tmp_path, "0001_baseline.py", "0001", None)
    _write_revision(tmp_path, "0002_next.py", "0002", "0001")
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(first)},
    }

    assert _run_main(payload, versions_dir=tmp_path, monkeypatch=monkeypatch) == ALLOW


def test_main_allows_when_tool_input_has_no_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {}}

    assert _run_main(payload, versions_dir=tmp_path, monkeypatch=monkeypatch) == ALLOW


def test_main_fails_open_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

    exit_code = main(versions_dir=VERSIONS_DIR)

    assert exit_code == ALLOW
    assert "could not parse hook payload" in capsys.readouterr().err


def test_the_script_lives_where_settings_json_can_point_at_it() -> None:
    """Anti-vacuity for the whole module: it resolves against the real repo."""
    script = REPO_ROOT / "scripts" / "hooks" / "guard_migrations.py"

    assert script.is_file()
    assert Path(__file__).resolve().parents[2] == REPO_ROOT

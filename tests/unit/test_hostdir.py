"""`app/hostdir.py`: the one place the app writes a file on the host (Phase 8 PD5, SD14)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.hostdir import prune, write_atomic
from app.jobs.naming import auto_pattern


def test_write_atomic_writes_the_final_name_and_no_partial(tmp_path: Path) -> None:
    written = write_atomic(tmp_path, "borrel-a-20261010-2000-manual.xlsx", b"PK\x03\x04")

    assert written == tmp_path / "borrel-a-20261010-2000-manual.xlsx"
    assert written.read_bytes() == b"PK\x03\x04"
    assert [p.name for p in tmp_path.iterdir()] == [written.name]


def test_a_second_write_of_the_same_name_replaces_it(tmp_path: Path) -> None:
    """PD7: two manual exports in one minute share a name; the later one wins."""
    write_atomic(tmp_path, "x.xlsx", b"first")
    write_atomic(tmp_path, "x.xlsx", b"second")

    assert (tmp_path / "x.xlsx").read_bytes() == b"second"


def test_the_directory_is_created_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "exports"

    write_atomic(target, "x.xlsx", b"data")

    assert (target / "x.xlsx").is_file()


def test_a_failure_between_write_and_rename_leaves_no_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader -- the laptop's Explorer, a USB copy -- never sees half a workbook."""

    def interrupted(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", interrupted)

    with pytest.raises(OSError, match="disk full"):
        write_atomic(tmp_path, "x.xlsx", b"data")

    assert not (tmp_path / "x.xlsx").exists()
    assert list(tmp_path.iterdir()) == []


def test_prune_keeps_the_newest_matches_by_name(tmp_path: Path) -> None:
    names = [f"borrel-a-20261010-20{m:02d}-auto.xlsx" for m in range(9)]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "borrel-a-20261010-1900-manual.xlsx").write_bytes(b"keep")
    (tmp_path / "borrel-b-20261010-1800-auto.xlsx").write_bytes(b"other slug")

    removed = prune(tmp_path, auto_pattern("a", 1), keep=8)

    assert removed == [tmp_path / names[0]]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [*names[1:], "borrel-a-20261010-1900-manual.xlsx", "borrel-b-20261010-1800-auto.xlsx"]
    )


def test_prune_ignores_partial_files(tmp_path: Path) -> None:
    (tmp_path / ".borrel-a-20261010-2000-auto.xlsx.partial").write_bytes(b"x")

    assert prune(tmp_path, auto_pattern("a", 1), keep=0) == []
    assert os.listdir(tmp_path) == [".borrel-a-20261010-2000-auto.xlsx.partial"]


def test_prune_leaves_a_run_whose_slug_extends_this_ones(tmp_path: Path) -> None:
    """Slug `borrel` must not take `borrel-oktober`'s files, nor lose its own newest."""
    longer = [f"borrel-borrel-oktober-20261010-20{m:02d}-auto.xlsx" for m in range(8)]
    newest = "borrel-borrel-20261011-2100-auto.xlsx"
    for name in [*longer, newest]:
        (tmp_path / name).write_bytes(b"x")

    assert prune(tmp_path, auto_pattern("Borrel", 1), keep=8) == []
    assert (tmp_path / newest).is_file()
    assert all((tmp_path / name).is_file() for name in longer)


def test_the_bytes_are_fsynced_before_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A power cut must not leave a final name on an empty file (AC21)."""
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        order.append("fsync")
        real_fsync(fd)

    def replace(src: Path, dst: Path) -> None:
        order.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)

    write_atomic(tmp_path, "x.xlsx", b"data")

    assert order == ["fsync", "replace"]

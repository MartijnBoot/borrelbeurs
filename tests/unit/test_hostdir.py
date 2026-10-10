"""`app/hostdir.py`: the one place the app writes a file on the host (Phase 8 PD5, SD14)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.hostdir import prune, write_atomic


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

    removed = prune(tmp_path, "borrel-a-*-auto.xlsx", keep=8)

    assert removed == [tmp_path / names[0]]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [*names[1:], "borrel-a-20261010-1900-manual.xlsx", "borrel-b-20261010-1800-auto.xlsx"]
    )


def test_prune_ignores_partial_files(tmp_path: Path) -> None:
    (tmp_path / ".borrel-a-20261010-2000-auto.xlsx.partial").write_bytes(b"x")

    assert prune(tmp_path, "borrel-a-*-auto.xlsx", keep=0) == []
    assert os.listdir(tmp_path) == [".borrel-a-20261010-2000-auto.xlsx.partial"]

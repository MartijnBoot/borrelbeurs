"""The v1 files the tests read are v1's, byte for byte (clean-up plan C5).

`legacy/v1/` was removed after cutover. The four files v2's tests still read --
the live config, the news file, the theme source and the API the market-event
and bar-price ports cite -- were copied first into `tests/fixtures/v1/`,
unchanged. `SHA256SUMS` pins each one, the same pin
`tests/engine/test_golden_capture.py` holds on `v1_reference/engine.py`: the
golden scenarios and the port tests mean something only while these are v1's
bytes. `.gitattributes` turns line-ending conversion off, so `backend/api.py`'s
CRLF blob is what every platform checks out and what its hash covers.

v1 as a whole is at tag `v2-rebuild-complete`, under `legacy/v1/`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v1"
SUMS = FIXTURES / "SHA256SUMS"


def mismatches(root: Path, sums: str) -> list[str]:
    """One line per pinned file that is missing or differs, and per unpinned file."""
    pinned: dict[str, str] = {}
    for line in sums.splitlines():
        digest, name = line.split(maxsplit=1)
        pinned[name] = digest
    found = []
    for name, digest in sorted(pinned.items()):
        path = root / name
        if not path.is_file():
            found.append(f"{name}: missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            found.append(f"{name}: changed")
    on_disk = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != root / "SHA256SUMS"
    }
    found.extend(f"{name}: not pinned" for name in sorted(on_disk - pinned.keys()))
    return found


def test_every_v1_fixture_is_v1_byte_for_byte() -> None:
    assert mismatches(FIXTURES, SUMS.read_text(encoding="utf-8")) == [], (
        "tests/fixtures/v1/ must never be edited; the golden scenarios and the port tests "
        "rest on it. Restore the file from tag v2-rebuild-complete (legacy/v1/)."
    )


def test_the_pins_cover_the_four_files_the_tests_read() -> None:
    names = {line.split(maxsplit=1)[1] for line in SUMS.read_text(encoding="utf-8").splitlines()}
    assert names == {
        "backend/api.py",
        "config/exchange_config.json",
        "static/news.json",
        "static/theme.js",
    }


def test_the_detector_flags_a_changed_a_missing_and_an_unpinned_file(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"{}")
    (tmp_path / "b.json").write_bytes(b"[]")
    (tmp_path / "extra.txt").write_bytes(b"x")
    sums = "\n".join(
        [
            f"{hashlib.sha256(b'{} ').hexdigest()}  a.json",
            f"{hashlib.sha256(b'[]').hexdigest()}  b.json",
            f"{hashlib.sha256(b'').hexdigest()}  gone.json",
        ]
    )
    assert mismatches(tmp_path, sums) == [
        "a.json: changed",
        "gone.json: missing",
        "extra.txt: not pinned",
    ]

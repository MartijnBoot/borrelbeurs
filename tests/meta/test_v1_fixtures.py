"""The v1 files the tests read are v1's, byte for byte (clean-up plan C5).

`legacy/v1/` was removed after cutover. The four files v2's tests still read --
the live config, the news file, the theme source and the API the market-event
and bar-price ports cite -- were copied first into `tests/fixtures/v1/`,
unchanged. `SHA256SUMS` pins each one, and this file hard-codes the same
digests -- the pin `tests/engine/test_golden_capture.py` holds on
`v1_reference/engine.py`, so a fixture cannot be edited with its sum: the
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


def test_sha256sums_holds_the_pins_written_here() -> None:
    # Hard-coded, like V1_ENGINE_SHA256: editing a fixture and SHA256SUMS together must fail.
    lines = SUMS.read_text(encoding="utf-8").splitlines()
    pinned = {name: digest for digest, name in (line.split(maxsplit=1) for line in lines)}
    assert pinned == {
        "backend/api.py": "43816cde142f218a54f67d7d99ada876deef56198c0bd2f0205bd6f9f84e6fed",
        "config/exchange_config.json": (
            "6aff447c35d29693e0752ca8ceb4f12b05aad9de835035b850573698dd66413e"
        ),
        "static/news.json": "94aeb2d1f95b0496a43379e486d9aaa8fb6e26b3780f69fda4cfe4d0c3c34747",
        "static/theme.js": "b8504258ea50f21e9fb92613d603ddf7b8e90d48c5c95b7de75b21267b212b8c",
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

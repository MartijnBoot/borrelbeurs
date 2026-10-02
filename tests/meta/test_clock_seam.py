"""SD32 — nothing under `app/runtime/` or `app/realtime/` reads time except `clock.py`.

The ticker, hub, limiter and session expiry take an injected `Clock`, so the
tests that count ticks and time out sockets run on a fake one (AC18a, AC22,
AC25). One stray `time.monotonic()` would quietly put real time back into
them. A walk over the syntax tree holds that, in `test_no_file_io.py`'s shape:
parse every file under the scanned roots and fail on `import time` or
`from time import ...` anywhere but `app/runtime/clock.py`.

**A guard that cannot fail is worse than no guard.** The walk must reach
`clock.py` itself and `app/realtime/messages.py`, and the detector must flag
each banned form in a snippet.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_ROOTS = (Path("app") / "runtime", Path("app") / "realtime")

THE_CLOCK = Path("app") / "runtime" / "clock.py"

MUST_SEE = (
    THE_CLOCK,
    Path("app") / "runtime" / "gap.py",
    Path("app") / "realtime" / "messages.py",
)


class Violation(NamedTuple):
    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def find_violations(source: str, path: Path) -> list[Violation]:
    """Every import of the `time` module in `source`, in line order."""
    found: list[Violation] = []
    for node in ast.walk(ast.parse(source, filename=path.as_posix())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] == "time":
                    found.append(Violation(path, node.lineno, f"`import {alias.name}`"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and (node.module or "").split(".", 1)[0] == "time"
        ):
            names = ", ".join(alias.name for alias in node.names)
            found.append(Violation(path, node.lineno, f"`from {node.module} import {names}`"))
    return sorted(found, key=lambda violation: violation.line)


def scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            files.append(path.relative_to(REPO_ROOT))
    return files


def test_only_the_clock_module_reads_time() -> None:
    """SD32, over the real tree."""
    violations: list[Violation] = []
    for relative_path in scanned_files():
        if relative_path == THE_CLOCK:
            continue
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        violations.extend(find_violations(source, relative_path))

    assert not violations, "\n".join(
        [
            f"{len(violations)} read(s) of `time` outside {THE_CLOCK.as_posix()}:",
            *(f"  {violation}" for violation in violations),
            "Take an injected `Clock` (app/runtime/clock.py) instead (SD32).",
        ]
    )


def test_the_clock_module_is_where_time_is_read() -> None:
    """Anti-vacuity: the detector, run on `clock.py` itself, does find its import."""
    source = (REPO_ROOT / THE_CLOCK).read_text(encoding="utf-8")

    assert find_violations(source, THE_CLOCK), "clock.py no longer imports time; is it a fake?"


def test_the_scan_reaches_the_real_source_tree() -> None:
    """Fail loudly if the walk stops finding files, instead of passing vacuously."""
    files = scanned_files()

    for root in SCANNED_ROOTS:
        assert (REPO_ROOT / root).is_dir(), f"{root.as_posix()}/ is missing; scanning nothing"
    for path in MUST_SEE:
        assert path in files, (
            f"{path.as_posix()} was not scanned; seen {[f.as_posix() for f in files]}"
        )


KNOWN_VIOLATIONS = [
    pytest.param("import time\n", 1, id="import-time"),
    pytest.param("import time as t\n", 1, id="import-time-as"),
    pytest.param("import os, time\n", 1, id="import-among-others"),
    pytest.param("from time import monotonic\n", 1, id="from-time-import"),
    pytest.param("from time import sleep as nap\n", 1, id="from-time-import-as"),
    pytest.param("def f():\n    import time\n", 2, id="local-import"),
]


@pytest.mark.parametrize(("source", "expected_line"), KNOWN_VIOLATIONS)
def test_detector_flags_each_banned_form(source: str, expected_line: int) -> None:
    violations = find_violations(source, Path("app/runtime/example.py"))

    assert [violation.line for violation in violations] == [expected_line]


BENIGN_SOURCES = [
    pytest.param("from datetime import time\n", id="datetime-time"),
    pytest.param("import datetime\n", id="datetime"),
    pytest.param("import timeit\n", id="timeit-is-not-time"),
    pytest.param("from .time import x\n", id="relative-module-named-time"),
    pytest.param("from app.runtime.clock import Clock\n", id="the-seam"),
]


@pytest.mark.parametrize("source", BENIGN_SOURCES)
def test_detector_permits_ordinary_code(source: str) -> None:
    assert find_violations(source, Path("app/runtime/example.py")) == []

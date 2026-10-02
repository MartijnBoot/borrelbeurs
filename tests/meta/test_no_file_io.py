"""AC18 — the repositories and the runtime read no file; the database is the store.

v1 kept its market in JSON and Excel files read on the request path (D-35).
Phase 2 moves every value into Postgres, so nothing under `app/db/` or
`app/runtime/` (the repositories, the ring, the aggregate, rehydrate) has any
business opening a file. A walk over the syntax tree holds that, modelled on
`test_config_boundary.py`: parse every file under the scanned roots and fail
on a banned reference.

Banned: a call to `open`, `io.open`, `os.open`, any `openpyxl` import,
`json.load` / `json.dump` (the string forms `loads` / `dumps` are the codec's
and fine), and `.read_text` / `.read_bytes` / `.write_text` / `.write_bytes` /
`.open` on anything. `json.load` is matched on `json` itself, not on `.load`
alone: `HistoryRing.load` is an ordinary method.

`app/cli/` is deliberately outside the scan: the v1 import is the one place
that reads files (AC18), and `app/cli/v1_files.py` says so. A root may only
ever be added here, never removed.

**A guard that cannot fail is worse than no guard.** As in
`test_config_boundary.py`, two tests exist only to stop a silently-empty scan:
the walk must reach real files, `app/db/runs.py` and `app/runtime/gap.py`
among them, and the detector must flag each banned form in a snippet.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_ROOTS = (Path("app") / "db", Path("app") / "runtime")

MUST_SEE = (
    Path("app") / "db" / "runs.py",
    Path("app") / "runtime" / "gap.py",
    Path("app") / "runtime" / "holder.py",
)

FILE_METHODS = frozenset({"read_text", "read_bytes", "write_text", "write_bytes", "open"})
JSON_FILE_FUNCTIONS = frozenset({"load", "dump"})


class Violation(NamedTuple):
    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def find_violations(source: str, path: Path) -> list[Violation]:
    """Every file-I/O reference in `source`, in line order. `path` is for reporting."""
    tree = ast.parse(source, filename=path.as_posix())
    found: list[Violation] = []

    def report(node: ast.AST, detail: str) -> None:
        found.append(Violation(path, getattr(node, "lineno", 0), detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] == "openpyxl":
                    report(node, f"`import {alias.name}`: spreadsheets are the import's alone")

        elif isinstance(node, ast.ImportFrom):
            package = (node.module or "").split(".", 1)[0]
            if package == "openpyxl":
                report(
                    node, f"`from {node.module} import ...`: spreadsheets are the import's alone"
                )
            elif package == "json":
                for alias in node.names:
                    if alias.name in JSON_FILE_FUNCTIONS or alias.name == "*":
                        report(node, f"`from json import {alias.name}` reads or writes a file")
            elif package in {"io", "os"}:
                for alias in node.names:
                    if alias.name in {"open", "*"}:
                        report(node, f"`from {package} import {alias.name}` opens a file")

        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "open":
                report(node, "`open()` opens a file")

        elif isinstance(node, ast.Attribute):
            if node.attr in FILE_METHODS:
                report(node, f"`.{node.attr}` touches a file")
            elif (
                node.attr in JSON_FILE_FUNCTIONS
                and isinstance(node.value, ast.Name)
                and node.value.id == "json"
            ):
                report(node, f"`json.{node.attr}` reads or writes a file")

    return sorted(found, key=lambda violation: (violation.line, violation.detail))


def scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            files.append(path.relative_to(REPO_ROOT))
    return files


def test_the_repositories_and_runtime_open_no_file() -> None:
    """AC18, over the real tree."""
    violations: list[Violation] = []
    for relative_path in scanned_files():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        violations.extend(find_violations(source, relative_path))

    assert not violations, "\n".join(
        [
            f"{len(violations)} file-I/O reference(s) in the repositories or runtime:",
            *(f"  {violation}" for violation in violations),
            "The database is the store (AC18); only app/cli/ reads files.",
        ]
    )


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
    pytest.param("with open('x') as f:\n    pass\n", 1, id="builtin-open"),
    pytest.param("import io\n\nf = io.open('x')\n", 3, id="io-open"),
    pytest.param("import os\n\nfd = os.open('x', 0)\n", 3, id="os-open"),
    pytest.param("from io import open\n", 1, id="from-io-import-open"),
    pytest.param("from os import open as o\n", 1, id="from-os-import-open"),
    pytest.param("import openpyxl\n", 1, id="import-openpyxl"),
    pytest.param("from openpyxl import load_workbook\n", 1, id="from-openpyxl"),
    pytest.param("import json\n\ndata = json.load(f)\n", 3, id="json-load"),
    pytest.param("import json\n\njson.dump(data, f)\n", 3, id="json-dump"),
    pytest.param("from json import load\n", 1, id="from-json-import-load"),
    pytest.param("from json import dump as d\n", 1, id="from-json-import-dump"),
    pytest.param("text = path.read_text()\n", 1, id="read-text"),
    pytest.param("raw = path.read_bytes()\n", 1, id="read-bytes"),
    pytest.param("path.write_text('x')\n", 1, id="write-text"),
    pytest.param("path.write_bytes(b'x')\n", 1, id="write-bytes"),
    pytest.param("with Path('x').open() as f:\n    pass\n", 1, id="path-open"),
]


@pytest.mark.parametrize(("source", "expected_line"), KNOWN_VIOLATIONS)
def test_detector_flags_each_banned_form(source: str, expected_line: int) -> None:
    violations = find_violations(source, Path("app/db/example.py"))

    assert expected_line in [violation.line for violation in violations], (
        f"expected a violation on line {expected_line}, got {[str(v) for v in violations]}"
    )


BENIGN_SOURCES = [
    pytest.param("import json\n\ntext = json.dumps({}, allow_nan=False)\n", id="json-dumps"),
    pytest.param("import json\n\ndata = json.loads('{}')\n", id="json-loads"),
    pytest.param("ring.load(entries)\n", id="history-ring-load"),
    pytest.param("async with engine.begin() as conn:\n    pass\n", id="engine-begin"),
]


@pytest.mark.parametrize("source", BENIGN_SOURCES)
def test_detector_permits_ordinary_code(source: str) -> None:
    assert find_violations(source, Path("app/db/example.py")) == []

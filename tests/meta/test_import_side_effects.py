"""R16 — importing this codebase must never touch the filesystem.

`legacy/v1/backend/config.py:11-13` is precisely how this goes wrong:
`os.makedirs(STATIC_DIR, exist_ok=True)` sitting at module level means merely
*importing* the module creates three directories -- in a test, in a build, in
a container being inspected. `app/core/config.py:5-11` promises the rewrite
does not repeat that, but until now the promise was only ever checked by
hand: nothing in the suite fails if a future `mkdir` creeps back in.

The mechanism is deliberately **not** `tests/meta/test_config_boundary.py`'s.
That file walks every reference in a file, anywhere, because an `os.environ`
read is a violation wherever it sits in the source. A filesystem mutation is
only a violation *at import time* -- the same `os.makedirs` call inside a
function is unremarkable, since it only runs when something calls the
function. So this guard walks **module-level statements only**: the
top-level body of each file, recursing into `if`/`with`/`try` blocks and
`class` bodies (which all run at import) and into a `def`'s decorators and
default values (evaluated when the `def` executes), but pruning the body of a
`def`/`async def`/`lambda` (which runs only when called).

Two name sets, not one:

- **Filesystem mutation** (`FS_MUTATION_NAMES`): `mkdir`, `makedirs` and
  friends -- the shape of the v1 regression -- plus the logging file
  handlers, which create their file on construction. `open` is judged by its
  mode instead of its name: `open(..., "w")` creates a file, but reads are
  deliberately not banned; `Path.read_text()` or `open(..., "r")` sitting at
  import is unremarkable, and banning them would buy false positives for no
  real risk covered elsewhere.
- **A second config loader** (`CONFIG_LOADER_NAMES`): `fileConfig`, mirroring
  `test_config_boundary.py`'s dotenv ban. `app/core/config.py` is the one
  place this application configures itself from something on disk; a second
  loader reading an `.ini` file (and potentially attaching a `FileHandler` to
  a logger) is exactly the kind of import-time surprise this file exists for.

**Why this depends on T5 and T7**, per the decision log
(`docs/plans/rebuild-progress.md`): T5 gives the guard a real `app/` to point
at, and T7 gives it a real `db/migrations/env.py` -- Alembic's own stock
template calls `fileConfig(config.config_file_name)` at module level, which
this guard would otherwise flag. Written blind, the exemption below would
either have been scaffolded loose enough to catch nothing, or would have
tripped on T7's first commit. `ALLOWED_MODULE_LEVEL_CALLS` is scoped to that
one call in that one file, not a blanket exemption for the file: any other
banned name appearing in `env.py` still fails.

**A guard that cannot fail is worse than no guard.** The same two safeguards
`test_config_boundary.py` uses: `test_the_scan_reaches_the_real_source_tree`
proves the walk found real files, and `test_the_allowlist_is_load_bearing`
proves the exemption is doing something -- that the real tree would fail
without it, not that it was decoration nobody needed.

Deliberately **not** covered here:

- **`rename`/`replace`/`remove`/`copy`**, all real filesystem operations and
  all excluded on purpose: every one collides with an everyday method on
  `str`, `list`, `dict` or `set`, and a name that fires on `data.remove(x)` or
  `text.replace(",", ";")` is pure false-positive surface for an operation
  `os.unlink`/`Path.unlink` already covers without the collision.
- **The second `BaseSettings` subclass gap** (also T4b's, per the decision
  log). That is a reference-shape question over the same roots
  `test_config_boundary.py` already walks, not a module-level-statement
  question, so it lives there instead of here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The trees this guard owns -- the same roots test_config_boundary.py scans.
SCANNED_ROOTS = ("app", "db")

# The v1 regression: directory/file creation, removal and mutation.
FS_MUTATION_NAMES = frozenset(
    {
        "mkdir",
        "makedirs",
        "removedirs",
        "rmdir",
        "unlink",
        "rmtree",
        "copytree",
        "write_text",
        "write_bytes",
        "touch",
        # Each creates its log file on construction.
        "FileHandler",
        "RotatingFileHandler",
        "TimedRotatingFileHandler",
    }
)

# `open`/`Path.open` is only a mutation in a writing mode, so it is judged on
# its mode argument rather than banned by name.
WRITE_MODE_CHARS = frozenset("wax+")
MODE_CHARS = frozenset("rwxabt+")

# A second door into file-based configuration, mirroring test_config_boundary
# .py's dotenv ban.
CONFIG_LOADER_NAMES = frozenset({"fileConfig"})

BANNED_NAMES = FS_MUTATION_NAMES | CONFIG_LOADER_NAMES

# Alembic's own entry point, never imported by app/ -- the alembic CLI execs
# it directly. Its one job includes loading its own logging config, a side
# effect the tool itself requires. Scoped to the exact call the stock
# template makes, not the whole file: any other banned name appearing in
# env.py still fails this guard.
ALLOWED_MODULE_LEVEL_CALLS: frozenset[tuple[Path, str]] = frozenset(
    {(Path("db/migrations/env.py"), "fileConfig")}
)


class Violation(NamedTuple):
    """One forbidden call, located precisely enough to go fix it."""

    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def _called_name(node: ast.Call) -> str:
    """The trailing identifier of the callee: `f`, `mod.f` and `a.b.f` all give `f`."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _opens_for_writing(node: ast.Call) -> bool:
    """`open(...)` or `Path(...).open(...)` with a literal writing mode.

    The mode may sit at either of the first two positions (`open(path, "w")`
    vs `Path(path).open("w")`), so both are checked; a string only counts as
    a mode if it is made purely of mode characters, which keeps a filename
    like `"data.txt"` from being mistaken for one. A non-literal mode is not
    judged -- nothing here can know what it holds.
    """
    if _called_name(node) != "open":
        return False
    candidates = [*node.args[:2], *(kw.value for kw in node.keywords if kw.arg == "mode")]
    return any(
        isinstance(arg, ast.Constant)
        and isinstance(arg.value, str)
        and arg.value
        and set(arg.value) <= MODE_CHARS
        and bool(set(arg.value) & WRITE_MODE_CHARS)
        for arg in candidates
    )


# Nodes whose `body` runs only when called. A `class` body is deliberately not
# here: it runs the moment the class is defined, which is at import.
DEFERRED_BODIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _iter_import_time_calls(node: ast.AST) -> Iterator[ast.Call]:
    """Every `Call` that runs merely by importing the module containing `node`.

    A manual walk, not `ast.walk`: `ast.walk` cannot be told to stop
    descending, and a function or lambda *body* must be pruned -- it runs only
    when called, never at import. `ast.walk` would otherwise report a
    `makedirs()` sitting harmlessly inside a function as an import-time
    violation. Only the body is pruned: a `def`'s decorators, defaults and
    annotations are evaluated at definition time, so they are still walked,
    as is a `class` body in full.
    """
    if isinstance(node, ast.Call):
        yield node
    for field, value in ast.iter_fields(node):
        if field == "body" and isinstance(node, DEFERRED_BODIES):
            continue
        for child in value if isinstance(value, list) else [value]:
            if isinstance(child, ast.AST):
                yield from _iter_import_time_calls(child)


def find_violations(
    source: str,
    path: Path,
    *,
    allowed: frozenset[tuple[Path, str]] = ALLOWED_MODULE_LEVEL_CALLS,
) -> list[Violation]:
    """Every banned call reachable from `source`'s module-level statements.

    `path` is used for reporting and for the allowlist check, so this works
    equally on a file read from disk and on a snippet written in a test.
    `allowed` defaults to the real allowlist; tests override it to prove that
    allowlist is load-bearing.
    """
    tree = ast.parse(source, filename=path.as_posix())
    found: list[Violation] = []

    for statement in tree.body:
        for call in _iter_import_time_calls(statement):
            name = _called_name(call)
            banned = name in BANNED_NAMES or _opens_for_writing(call)
            if not banned or (path, name) in allowed:
                continue
            verb = (
                "loads configuration from disk"
                if name in CONFIG_LOADER_NAMES
                else "touches the filesystem"
            )
            found.append(Violation(path, call.lineno, f"`{name}(...)` {verb} at import"))

    return sorted(found, key=lambda violation: (violation.line, violation.detail))


def scanned_files() -> list[Path]:
    """Every Python file under the guarded roots, relative to the repository root."""
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            files.append(path.relative_to(REPO_ROOT))
    return files


def test_no_module_level_filesystem_side_effects_in_the_real_tree() -> None:
    """R16, over the real tree."""
    violations: list[Violation] = []
    for relative_path in scanned_files():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        violations.extend(find_violations(source, relative_path))

    assert not violations, "\n".join(
        [
            f"{len(violations)} filesystem side effect(s) at import:",
            *(f"  {violation}" for violation in violations),
            "Move the call inside a function, or -- if it is genuinely needed at "
            "import, like Alembic's own env.py -- add it to "
            "ALLOWED_MODULE_LEVEL_CALLS with a reason (R16).",
        ]
    )


def test_the_scan_reaches_the_real_source_tree() -> None:
    """Fail loudly if the walk stops finding files, instead of passing vacuously."""
    files = scanned_files()

    for root in SCANNED_ROOTS:
        assert (REPO_ROOT / root).is_dir(), f"{root}/ is missing; the guard is scanning nothing"

    for expected in (Path("app/main.py"), Path("db/migrations/env.py")):
        assert expected in files, (
            f"{expected.as_posix()} was not found by the scan. Either it moved -- in "
            f"which case this assertion should move with it -- or REPO_ROOT resolves "
            f"somewhere wrong and this guard is checking an empty tree. Files seen: "
            f"{[f.as_posix() for f in files]}"
        )


def test_the_allowlist_is_load_bearing() -> None:
    """Prove the exemption is doing something, not decoration nobody needed.

    Without it, `db/migrations/env.py`'s own `fileConfig` call -- Alembic's
    stock template, not this project's code -- fails the real-tree test
    above. That test therefore passes *because of* this exemption, not in
    spite of an empty one.
    """
    source = (REPO_ROOT / "db" / "migrations" / "env.py").read_text(encoding="utf-8")

    violations = find_violations(source, Path("db/migrations/env.py"), allowed=frozenset())

    assert violations, (
        "expected db/migrations/env.py's fileConfig call to trip with an empty "
        "allowlist; either the call was removed (delete the now-unused allowlist "
        "entry) or this guard stopped seeing it"
    )


KNOWN_VIOLATIONS = [
    pytest.param(
        "import os\n\nos.makedirs('static', exist_ok=True)\n", 3, id="os-makedirs-the-v1-regression"
    ),
    pytest.param("import os\n\nos.mkdir('static')\n", 3, id="os-mkdir"),
    pytest.param(
        "from os import makedirs\n\nmakedirs('static')\n", 3, id="from-os-import-makedirs"
    ),
    pytest.param("import os as system\n\nsystem.makedirs('static')\n", 3, id="aliased-os-module"),
    pytest.param("import shutil\n\nshutil.rmtree('build')\n", 3, id="shutil-rmtree"),
    pytest.param("import shutil\n\nshutil.copytree('a', 'b')\n", 3, id="shutil-copytree"),
    pytest.param(
        "from pathlib import Path\n\nPath('x').write_text('y')\n", 3, id="path-write-text"
    ),
    pytest.param("from pathlib import Path\n\nPath('x').touch()\n", 3, id="path-touch"),
    pytest.param(
        "from logging.config import fileConfig\n\nfileConfig('x.ini')\n",
        3,
        id="fileconfig-outside-the-allowlisted-file",
    ),
    pytest.param(
        "import os\n\nif True:\n    os.makedirs('static')\n",
        4,
        id="inside-a-module-level-if",
    ),
    pytest.param(
        "import os\n\nclass Paths:\n    os.makedirs('static')\n",
        4,
        id="inside-a-class-body-which-runs-at-import",
    ),
    pytest.param(
        "import os\n\n@os.makedirs('static')\ndef f() -> None:\n    pass\n",
        3,
        id="in-a-decorator-expression",
    ),
    pytest.param(
        "import os\n\ndef f(x: None = os.makedirs('static')) -> None:\n    pass\n",
        3,
        id="in-a-default-argument",
    ),
    pytest.param("LOG = open('out.log', 'w')\n", 1, id="open-for-writing"),
    pytest.param("LOG = open('out.log', mode='a')\n", 1, id="open-append-by-keyword"),
    pytest.param(
        "from pathlib import Path\n\nLOG = Path('out.log').open('w')\n",
        3,
        id="path-open-for-writing",
    ),
    pytest.param(
        "import logging\n\nHANDLER = logging.FileHandler('app.log')\n", 3, id="logging-filehandler"
    ),
]


@pytest.mark.parametrize(("source", "expected_line"), KNOWN_VIOLATIONS)
def test_detector_flags_a_real_violation(source: str, expected_line: int) -> None:
    """The guard's own regression suite: each snippet is a way in it must close."""
    violations = find_violations(source, Path("app/main.py"))

    assert violations, f"no violation reported for:\n{source}"
    assert expected_line in [violation.line for violation in violations], (
        f"expected a violation on line {expected_line}, got {[str(v) for v in violations]}"
    )


def test_a_violation_reports_file_and_line() -> None:
    """The failure message must point at a location, not just assert a rule."""
    violations = find_violations("import os\n\nos.makedirs('x')\n", Path("app/main.py"))

    assert str(violations[0]).startswith("app/main.py:3: ")


def test_the_allowlisted_call_is_permitted() -> None:
    """The one call the allowlist exists for, in the one file it names."""
    source = "from logging.config import fileConfig\n\nfileConfig('x.ini')\n"

    assert find_violations(source, Path("db/migrations/env.py")) == []


BENIGN_SOURCES = [
    pytest.param(
        "import os\n\ndef setup() -> None:\n    os.makedirs('static')\n",
        id="mkdir-inside-a-function",
    ),
    pytest.param(
        "import os\n\nclass Setup:\n    def run(self) -> None:\n        os.makedirs('static')\n",
        id="mkdir-inside-a-method",
    ),
    pytest.param(
        "import os\n\nsetup = lambda: os.makedirs('static')\n",
        id="mkdir-inside-a-lambda",
    ),
    pytest.param(
        "from pathlib import Path\n\nCONTENT = Path('x').read_text()\n", id="path-read-text"
    ),
    pytest.param("CONTENT = open('x.txt').read()\n", id="open-with-no-mode-is-a-read"),
    pytest.param("CONTENT = open('x.bin', 'rb').read()\n", id="open-for-reading-binary"),
    pytest.param(
        "from pathlib import Path\n\nCONTENT = Path('data.txt').open().read()\n",
        id="path-open-filename-is-not-a-mode",
    ),
    pytest.param("data = [1, 2, 3]\n\ndata.remove(2)\n", id="list-remove-not-os-remove"),
    pytest.param(
        "text = 'a,b'\n\nresult = text.replace(',', ';')\n", id="str-replace-not-path-replace"
    ),
    pytest.param("import os\n\nBASE = os.path.join('a', 'b')\n", id="os-path-join"),
    pytest.param("config = {}\n\nsnapshot = config.copy()\n", id="dict-copy-not-shutil-copytree"),
]


@pytest.mark.parametrize("source", BENIGN_SOURCES)
def test_detector_permits_ordinary_code(source: str) -> None:
    """A banned name inside a function, or an everyday method with the same
    name as a banned one, is not the offence; a module-level filesystem
    mutation is."""
    assert find_violations(source, Path("app/main.py")) == []

"""AC3 — the environment is read in one module, and the tree says so.

`app/core/config.py` owns `os.environ`. Everything else takes a `Settings`
instance. Stated in a docstring that rule survives until the first hurried
evening; enforced by a walk over the syntax tree it survives the project.

The mechanism: parse every file under `app/` and `db/`, walk each syntax tree,
fail on a forbidden reference. `import os` is perfectly fine in `app/` (paths,
signals) and only `os.environ` and its relatives are not, so the predicate is a
set of *references* rather than a set of imports.

That is a deliberately different shape from the purity test
[architecture.md:87-89](../../docs/design/architecture.md#L87-L89) prescribes
for `exchange/`, which walks the package's *transitive imports* and bans whole
modules. The difference is a real gap and worth naming: this guard selects
files by location, so a first-party module living outside `app/` and `db/`
could read the environment and be imported by `app/` without this test seeing
it. Today the only such tree is `exchange/`, from which Phase 1's purity test
bans `os` outright — which is why an import walk here would buy nothing.

**A guard that cannot fail is worse than no guard.** `db/` is empty today and
will stay that way until T7, so a mis-rooted or silently-empty scan would pass
green forever. Two tests below exist solely to stop that:
`test_the_scan_reaches_the_real_source_tree` asserts the walk found real files
including the config module itself, and `test_detector_flags_a_real_violation`
runs the detector over snippets of the code it is meant to catch.

Deliberately **not** covered here:

- `uvicorn --env-file` and any other launch-flag route into the environment
  (R12). That is a property of how the process is started, not of the syntax
  tree; it belongs to T5's app shell and T9's `check.sh`.
- Filesystem side effects at import (R16). A different predicate needing a
  different walk (module-level statements only) and its own allowlist — see the
  handover note rather than bolting it onto this one.
- `legacy/v1/**` (frozen v1 reference) and `exchange/**` (the pure engine,
  entering the gate in Phase 1). Both are excluded from ruff and mypy as well
  (`pyproject.toml:52`, `pyproject.toml:63`); this is plan D13, settled.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The trees this guard owns.
SCANNED_ROOTS = ("app", "db")

# The one file permitted to read the environment.
CONFIG_MODULE = Path("app") / "core" / "config.py"

# Attribute (or bare name) references that mean "the process environment".
# `putenv`/`unsetenv` are writes rather than reads; AC3 says "read", but nothing
# in `app/` or `db/` has any business mutating the environment either, and a
# rule with no exceptions is cheaper to keep than one with a footnote.
ENV_NAMES = frozenset({"environ", "environb", "getenv", "putenv", "unsetenv"})

# The write half of the set above. Split out for the failure message only: a
# developer who trips this rule should be told what their code actually does.
ENV_WRITE_NAMES = frozenset({"putenv", "unsetenv"})

# python-dotenv's entry points. Names generic enough to collide with ordinary
# application vocabulary (`get_key`, `set_key`) are left out on purpose — any
# *import* of dotenv is caught outright below, which is the real signal.
DOTENV_NAMES = frozenset({"load_dotenv", "dotenv_values", "find_dotenv"})

# Modules that may not be reached for by name at runtime either.
DYNAMIC_IMPORT_TARGETS = frozenset({"dotenv"})


class Violation(NamedTuple):
    """One forbidden reference, located precisely enough to go fix it."""

    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def _top_level_package(module: str) -> str:
    return module.split(".", 1)[0]


def _string_argument(node: ast.Call, index: int) -> str | None:
    """The `index`-th positional argument, if it is a plain string literal."""
    if len(node.args) <= index:
        return None
    argument = node.args[index]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def _called_name(node: ast.Call) -> str:
    """The trailing identifier of the callee: `f`, `mod.f` and `a.b.f` all give `f`."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_violation(node: ast.Call) -> str | None:
    """Detail for the two indirections cheap enough to be worth closing."""
    name = _called_name(node)

    # getattr(os, "environ") — the attribute access written as a string.
    if name == "getattr":
        attribute = _string_argument(node, 1)
        if attribute in ENV_NAMES:
            return f'getattr(..., "{attribute}") reaches the environment indirectly'

    # importlib.import_module("dotenv") / __import__("dotenv").
    if name in {"import_module", "__import__"}:
        module = _string_argument(node, 0)
        if module is not None and _top_level_package(module) in DYNAMIC_IMPORT_TARGETS:
            return f"imports `{module}` dynamically; .env loading is not this module's job"

    return None


def find_violations(source: str, path: Path) -> list[Violation]:
    """Every environment reference in `source`, in line order.

    `path` is used for reporting only, so this works equally on a file read
    from disk and on a snippet written in a test.
    """
    tree = ast.parse(source, filename=path.as_posix())
    found: list[Violation] = []

    def report(node: ast.AST, detail: str) -> None:
        found.append(Violation(path, getattr(node, "lineno", 0), detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # `import os` is fine — os.path, os.sep, os.fspath all are. Only the
            # environment is off limits, and that is caught at the reference.
            for alias in node.names:
                if _top_level_package(alias.name) == "dotenv":
                    report(node, f"`import {alias.name}`: only app/core/config.py may load .env")

        elif isinstance(node, ast.ImportFrom):
            package = _top_level_package(node.module or "")
            if package == "dotenv":
                report(node, f"`from {node.module} import ...`: .env loading is config's alone")
            elif package == "os":
                for alias in node.names:
                    if alias.name in ENV_NAMES:
                        report(node, f"`from os import {alias.name}`: take a Settings instead")
                    elif alias.name == "*":
                        report(node, "`from os import *` pulls in environ and getenv")

        elif isinstance(node, ast.Attribute):
            # Matched on the attribute alone, not on `os.<attr>`, so that
            # `import os as system` and `sys.modules["os"].environ` are caught
            # too. False positives are conceivable and have never appeared.
            if node.attr in ENV_NAMES:
                verb = "writes" if node.attr in ENV_WRITE_NAMES else "reads"
                report(node, f"`.{node.attr}` {verb} the process environment")
            elif node.attr in DOTENV_NAMES:
                report(node, f"`.{node.attr}()` loads a .env file")

        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            # Only dotenv's entry points. A bare `environ` or `getenv` is far
            # more often an ordinary local — a WSGI `environ` parameter, say —
            # than an escapee from `os`, and every route from `os` to a bare
            # name runs through an import statement already caught above.
            if node.id in DOTENV_NAMES:
                report(node, f"`{node.id}()` loads a .env file")

        elif isinstance(node, ast.Call):
            detail = _call_violation(node)
            if detail is not None:
                report(node, detail)

    return sorted(found, key=lambda violation: (violation.line, violation.detail))


def scanned_files() -> list[Path]:
    """Every Python file under the guarded roots, relative to the repository root."""
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            files.append(path.relative_to(REPO_ROOT))
    return files


def test_the_environment_is_read_only_in_the_config_module() -> None:
    """AC3, over the real tree."""
    violations: list[Violation] = []
    for relative_path in scanned_files():
        if relative_path == CONFIG_MODULE:
            continue
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        violations.extend(find_violations(source, relative_path))

    assert not violations, "\n".join(
        [
            f"{len(violations)} environment reference(s) outside {CONFIG_MODULE.as_posix()}:",
            *(f"  {violation}" for violation in violations),
            "Inject a Settings from app.core.config instead (spec AC3).",
        ]
    )


def test_the_scan_reaches_the_real_source_tree() -> None:
    """Fail loudly if the walk stops finding files, instead of passing vacuously.

    `db/` is legitimately empty until T7, so the only load-bearing assertion is
    that `app/` — and specifically the module the test exempts — was seen.
    """
    files = scanned_files()

    for root in SCANNED_ROOTS:
        assert (REPO_ROOT / root).is_dir(), f"{root}/ is missing; the guard is scanning nothing"

    assert CONFIG_MODULE in files, (
        f"{CONFIG_MODULE.as_posix()} was not found by the scan. Either the config module "
        f"moved — in which case update CONFIG_MODULE — or REPO_ROOT resolves somewhere wrong "
        f"and this guard is checking an empty tree. Files seen: {[f.as_posix() for f in files]}"
    )


KNOWN_VIOLATIONS = [
    pytest.param("import os\n\nDSN = os.environ['DATABASE_URL']\n", 3, id="os-environ-subscript"),
    pytest.param("import os\n\nDSN = os.environ.get('X')\n", 3, id="os-environ-get"),
    pytest.param("import os\n\nfor key in os.environ:\n    print(key)\n", 3, id="os-environ-loop"),
    pytest.param("import os\n\nDSN = os.getenv('X', '')\n", 3, id="os-getenv"),
    pytest.param("from os import environ\n", 1, id="from-os-import-environ"),
    pytest.param("from os import getenv as g\n\nDSN = g('X')\n", 1, id="from-os-import-aliased"),
    pytest.param("from os import *\n", 1, id="from-os-import-star"),
    pytest.param("import os as system\n\nDSN = system.environ['X']\n", 3, id="aliased-os-module"),
    pytest.param("import os\n\nos.putenv('X', 'y')\n", 3, id="os-putenv"),
    pytest.param("import dotenv\n", 1, id="import-dotenv"),
    pytest.param("from dotenv import load_dotenv\n\nload_dotenv()\n", 1, id="from-dotenv-import"),
    pytest.param("load_dotenv()\n", 1, id="bare-load-dotenv"),
    pytest.param("import os\n\nDSN = getattr(os, 'environ')['X']\n", 3, id="getattr-environ"),
    # No trailing `.load_dotenv()`: with one, the Attribute branch reports the
    # same line and the case passes even when the dynamic-import branch is
    # deleted — testing nothing. This form is sourced from that branch alone.
    pytest.param(
        "import importlib\n\nmodule = importlib.import_module('dotenv')\n",
        3,
        id="dynamic-dotenv-import",
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
    violations = find_violations("import os\n\nDSN = os.getenv('X')\n", Path("app/main.py"))

    assert str(violations[0]).startswith("app/main.py:3: ")


BENIGN_SOURCES = [
    pytest.param("import os\n\nPATH = os.path.join('a', 'b')\n", id="os-path"),
    pytest.param("from os import sep\n", id="from-os-import-sep"),
    pytest.param("import os\n\nSIZE = os.fspath('a')\n", id="os-fspath"),
    pytest.param(
        "from app.core.config import get_settings\n\nDSN = get_settings().database_url\n",
        id="the-sanctioned-route",
    ),
]


@pytest.mark.parametrize("source", BENIGN_SOURCES)
def test_detector_permits_ordinary_code(source: str) -> None:
    """`import os` is not the offence; reading the environment is."""
    assert find_violations(source, Path("app/main.py")) == []

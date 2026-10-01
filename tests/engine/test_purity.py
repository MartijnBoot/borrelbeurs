"""AC2 -- the `exchange` package imports no clock, no I/O, no framework.

The walk starts at `exchange/__init__.py`, parses each module it reaches, and
follows every import into the package: `import exchange.x`, `from exchange.x
import y`, `from exchange import x` (x a submodule), relative imports, and
`importlib.import_module` / `__import__` called with a string literal. Every
other import's top-level package is checked against the ban list and *not*
descended into (plan D8): numpy itself imports `os`, so following third-party
code would make AC2 unsatisfiable rather than strict.

Imports anywhere in a module count -- inside a function too -- because a
deferred `import time` is still the engine reading the clock.

**A guard that cannot fail is worse than no guard.** Two tests below keep this
one honest, the same shape as `tests/meta/test_config_boundary.py`: the walk
must reach every `.py` file under `exchange/` (a module it cannot reach is
either dead or imported in a way the walk does not understand -- both fail),
and the detector is run over snippets of each banned form.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "exchange"

# AC2's list, verbatim. Adding to it is a question for the human (plan T8).
BANNED = frozenset(
    {"time", "datetime", "random", "os", "asyncio", "sqlalchemy", "fastapi", "openpyxl"}
)


class Violation(NamedTuple):
    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(module: str, root: Path) -> Path | None:
    """The file for a first-party module name, if one exists under `root`."""
    base = root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(tree: ast.AST, current: str, is_package: bool) -> list[tuple[int, str]]:
    """Every module `tree` imports, as (line, absolute dotted name)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = current.split(".") if is_package else current.split(".")[:-1]
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            found.append((node.lineno, base))
            # `from pkg import name` may name a submodule: try both.
            found.extend((node.lineno, f"{base}.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((node.lineno, arg.value))
    return found


def walk(root: Path, package: str) -> tuple[set[Path], list[Violation]]:
    """Every module reachable from `package/__init__.py`, and every banned import in them."""
    entry = root / package / "__init__.py"
    reached: set[Path] = set()
    violations: list[Violation] = []
    queue = [entry]
    while queue:
        path = queue.pop()
        if path in reached:
            continue
        reached.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        current = _module_name(path, root)
        for line, module in _imports(tree, current, path.name == "__init__.py"):
            if _top(module) == package:
                target = _resolve(module, root)
                if target is not None:
                    queue.append(target)
            elif _top(module) in BANNED:
                violations.append(
                    Violation(path.relative_to(root), line, f"imports `{module}` (AC2)")
                )
    return reached, sorted(violations)


# --- the real package --------------------------------------------------------------------


def test_the_exchange_package_imports_nothing_banned() -> None:
    _, violations = walk(REPO_ROOT, PACKAGE)
    assert not violations, "\n".join(str(v) for v in violations)


def test_the_walk_reaches_every_module_in_the_package() -> None:
    reached, _ = walk(REPO_ROOT, PACKAGE)
    on_disk = set((REPO_ROOT / PACKAGE).rglob("*.py"))
    unreached = sorted(p.relative_to(REPO_ROOT).as_posix() for p in on_disk - reached)
    assert not unreached, f"not reachable from exchange/__init__.py: {unreached}"


def test_the_walk_reaches_the_engine_modules() -> None:
    reached, _ = walk(REPO_ROOT, PACKAGE)
    names = {p.stem for p in reached}
    assert {"__init__", "pricing", "spec", "state", "steps", "advance"} <= names


# --- the detector, on snippets ------------------------------------------------------------


def _walk_snippets(tmp_path: Path, files: dict[str, str]) -> tuple[set[str], list[Violation]]:
    for name, source in files.items():
        path = tmp_path / "pkg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    reached, violations = walk(tmp_path, "pkg")
    return {p.relative_to(tmp_path / "pkg").as_posix() for p in reached}, violations


@pytest.mark.parametrize(
    "source",
    [
        "import time\n",
        "import os.path\n",
        "import asyncio as aio\n",
        "from datetime import datetime\n",
        "from random import random\n",
        "from sqlalchemy.orm import Session\n",
        "def f() -> None:\n    import fastapi\n",
        "import importlib\nimportlib.import_module('openpyxl')\n",
        "__import__('time')\n",
        "from time import *\n",
    ],
)
def test_each_banned_form_is_flagged(tmp_path: Path, source: str) -> None:
    _, violations = _walk_snippets(tmp_path, {"__init__.py": source})
    assert violations, source
    assert violations[0].path.as_posix() == "pkg/__init__.py"
    assert violations[0].line >= 1


@pytest.mark.parametrize(
    "files",
    [
        pytest.param({"__init__.py": "from . import inner\n"}, id="from-dot-import"),
        pytest.param({"__init__.py": "from .inner import x\n"}, id="relative-from"),
        pytest.param({"__init__.py": "import pkg.inner\n"}, id="absolute-import"),
        pytest.param({"__init__.py": "from pkg import inner\n"}, id="from-package-import"),
        pytest.param({"__init__.py": "from pkg.inner import x\n"}, id="absolute-from"),
        pytest.param(
            {"__init__.py": "import importlib\nimportlib.import_module('pkg.inner')\n"},
            id="dynamic",
        ),
    ],
)
def test_the_walk_follows_every_import_form_into_the_package(
    tmp_path: Path, files: dict[str, str]
) -> None:
    reached, violations = _walk_snippets(
        tmp_path, {**files, "inner.py": "x = 1\nimport datetime\n"}
    )
    assert "inner.py" in reached
    assert [str(v) for v in violations] == ["pkg/inner.py:2: imports `datetime` (AC2)"]


def test_a_relative_import_from_a_subpackage_resolves_upwards(tmp_path: Path) -> None:
    reached, violations = _walk_snippets(
        tmp_path,
        {
            "__init__.py": "from .sub import mod\n",
            "sub/__init__.py": "",
            "sub/mod.py": "from ..helpers import h\n",
            "helpers.py": "import random\nh = 1\n",
        },
    )
    assert {"sub/mod.py", "helpers.py"} <= reached
    assert [v.path.as_posix() for v in violations] == ["pkg/helpers.py"]


def test_an_unreached_module_is_reported(tmp_path: Path) -> None:
    reached, _ = _walk_snippets(tmp_path, {"__init__.py": "", "orphan.py": "x = 1\n"})
    assert "orphan.py" not in reached


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\n",
        "from numpy.random import SeedSequence, default_rng\n",
        "import dataclasses\nfrom typing import Any\n",
        "import timeit\nimport osmosis\nimport randomness\n",
        "import math\nfrom collections.abc import Mapping\n",
    ],
)
def test_ordinary_imports_are_permitted(tmp_path: Path, source: str) -> None:
    _, violations = _walk_snippets(tmp_path, {"__init__.py": source})
    assert not violations

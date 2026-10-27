"""B-11 AC19 — the cheap argon2 parameters live in `tests/api/conftest.py` and nowhere else.

`tests/api` swaps `app.api.security._KEY_PARAMS` for minimal ones (SD7). Anywhere
else the swap would hide what production hashes cost, or break the pin and the
known-answer hash `tests/unit/test_short_keys.py` holds. A walk over the syntax
tree of every Python file under the scanned roots fails on any write to
`_KEY_PARAMS` outside that one conftest: a `setattr`/`patch` naming it, an
assignment to `<module>._KEY_PARAMS`, or a mutation of it in place. Reading it
(the unit pin does) is fine; its one definition in `app/api/security.py` is a
plain name, not an attribute, and is not a write by these rules.

**A guard that cannot fail is worse than no guard.** The walk must reach the
conftest itself and find the swap there, and the detector must flag each form in
a planted file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = ("app", "db", "scripts", "tests")
EXCLUDED = (Path("tests") / "engine" / "v1_reference", Path("tests") / "fixtures" / "v1")
THE_SWAP = Path("tests") / "api" / "conftest.py"
NAME = "_KEY_PARAMS"
MUTATORS = frozenset({"update", "__setitem__", "setdefault", "pop", "clear"})


def _names_it(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == NAME) or (
        isinstance(node, ast.Attribute) and node.attr == NAME
    )


def find_swaps(source: str, path: Path) -> list[int]:
    """The lines in `source` that write `_KEY_PARAMS`."""
    tree = ast.parse(source, filename=path.as_posix())
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            named = any(
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.split(".")[-1] == NAME
                for arg in node.args
            )
            mutated = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATORS
                and _names_it(node.func.value)
            )
            if named or mutated:
                lines.append(node.lineno)
        elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (isinstance(target, ast.Attribute) and target.attr == NAME) or (
                    isinstance(target, ast.Subscript) and _names_it(target.value)
                ):
                    lines.append(node.lineno)
    return sorted(lines)


def _python_files() -> list[Path]:
    return sorted(
        path.relative_to(REPO_ROOT)
        for root in SCANNED_ROOTS
        for path in (REPO_ROOT / root).rglob("*.py")
        if not any(excluded in path.relative_to(REPO_ROOT).parents for excluded in EXCLUDED)
    )


def test_the_swap_is_made_only_in_the_api_conftest() -> None:
    elsewhere = [
        f"{path.as_posix()}:{line}"
        for path in _python_files()
        if path != THE_SWAP
        for line in find_swaps((REPO_ROOT / path).read_text(encoding="utf-8"), path)
    ]
    assert elsewhere == []


def test_the_walk_reaches_the_conftest_and_finds_the_swap_there() -> None:
    files = _python_files()
    assert THE_SWAP in files
    assert Path("app") / "api" / "security.py" in files
    assert find_swaps((REPO_ROOT / THE_SWAP).read_text(encoding="utf-8"), THE_SWAP)


@pytest.mark.parametrize(
    "source",
    [
        "def f(monkeypatch, security):\n    monkeypatch.setattr(security, '_KEY_PARAMS', {})\n",
        "from unittest import mock\nmock.patch('app.api.security._KEY_PARAMS', {})\n",
        "from app.api import security\nsecurity._KEY_PARAMS = {}\n",
        "from app.api import security\nsecurity._KEY_PARAMS['time_cost'] = 1\n",
        "from app.api.security import _KEY_PARAMS\n_KEY_PARAMS.update(time_cost=1)\n",
    ],
    ids=["setattr", "patch", "assign", "subscript", "update"],
)
def test_a_planted_swap_is_found(tmp_path: Path, source: str) -> None:
    planted = tmp_path / "test_planted.py"
    planted.write_text(source, encoding="utf-8")
    assert find_swaps(planted.read_text(encoding="utf-8"), Path("tests/unit/test_planted.py"))


def test_reading_the_parameters_is_not_a_swap() -> None:
    source = "from app.api import security\npinned = security._KEY_PARAMS\ncost = pinned['x']\n"
    assert find_swaps(source, Path("tests/unit/test_short_keys.py")) == []

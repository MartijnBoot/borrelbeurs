"""B-11 AC4 — a test module that starts the real app is marked `serial` as a whole.

SD3's rule: a test that starts a real `python -m app.main`, or asserts a bound on
real elapsed time, runs in the gate's serial stage. The second half needs a
reader (the plan's serial list); the first can be held by a walk over the syntax
tree. Every `tests/**/test_*.py` but `tests/image` (the drills against a built
image, never collected by the gate) that imports or calls the real-app harness's
`spawn_app` or `start_app` must say `pytestmark = pytest.mark.serial` (or a list
holding it) at module level.

**A guard that cannot fail is worse than no guard.** The walk must reach the
modules known to start the app, and the detector must flag a planted module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_STARTERS = frozenset({"spawn_app", "start_app"})
EXCLUDED = Path("tests") / "image"

MUST_SEE = (
    Path("tests") / "integration" / "test_real_process.py",
    Path("tests") / "integration" / "test_db_restart.py",
)


def starts_the_app(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name in HARNESS_STARTERS for alias in node.names
        ):
            return True
        if isinstance(node, ast.Name) and node.id in HARNESS_STARTERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in HARNESS_STARTERS:
            return True
    return False


def _is_serial_mark(node: ast.expr) -> bool:
    """`pytest.mark.serial` or `mark.serial`."""
    return isinstance(node, ast.Attribute) and node.attr == "serial"


def module_is_serial(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        value = node.value
        marks = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        if any(_is_serial_mark(mark) for mark in marks):
            return True
    return False


def find_violation(source: str, path: Path) -> str | None:
    """A message naming `path` if it starts the app without being serial, else `None`."""
    tree = ast.parse(source, filename=path.as_posix())
    if starts_the_app(tree) and not module_is_serial(tree):
        return (
            f"{path.as_posix()}: starts the real app (`spawn_app`/`start_app`) but is not "
            "marked `pytestmark = pytest.mark.serial` (B-11 SD3)"
        )
    return None


def _test_modules() -> list[Path]:
    return sorted(
        path.relative_to(REPO_ROOT)
        for path in (REPO_ROOT / "tests").rglob("test_*.py")
        if EXCLUDED not in path.relative_to(REPO_ROOT).parents
    )


def test_every_module_that_starts_the_app_is_serial() -> None:
    violations = [
        message
        for path in _test_modules()
        if (message := find_violation((REPO_ROOT / path).read_text(encoding="utf-8"), path))
    ]
    assert violations == []


def test_the_walk_reaches_the_modules_that_start_the_app() -> None:
    modules = _test_modules()
    assert all(path in modules for path in MUST_SEE)
    assert not any(EXCLUDED in path.parents for path in modules)
    starters = [p for p in modules if starts_the_app(ast.parse((REPO_ROOT / p).read_text("utf-8")))]
    assert all(path in starters for path in MUST_SEE)


@pytest.mark.parametrize(
    "source",
    [
        "from tests.integration.realapp.harness import start_app\n",
        "from tests.integration.realapp import harness\n\ndef t():\n    harness.spawn_app()\n",
        "import pytest\nfrom tests.integration.realapp.harness import spawn_app\n"
        "pytestmark = pytest.mark.slow\n",
        "import pytest\nfrom tests.integration.realapp.harness import start_app\n"
        "@pytest.mark.serial\ndef test_x():\n    start_app()\n",
    ],
    ids=["import", "attribute-call", "another-mark", "per-test-mark-only"],
)
def test_a_planted_module_that_starts_the_app_unmarked_is_named(
    tmp_path: Path, source: str
) -> None:
    planted = tmp_path / "test_planted.py"
    planted.write_text(source, encoding="utf-8")
    message = find_violation(planted.read_text(encoding="utf-8"), Path("tests/test_planted.py"))
    assert message is not None
    assert "tests/test_planted.py" in message


@pytest.mark.parametrize(
    "mark",
    ["pytest.mark.serial", "[pytest.mark.serial, pytest.mark.slow]", "(pytest.mark.serial,)"],
)
def test_a_marked_module_passes(mark: str) -> None:
    source = (
        f"import pytest\nfrom tests.integration.realapp.harness import start_app\n"
        f"pytestmark = {mark}\n"
    )
    assert find_violation(source, Path("tests/test_ok.py")) is None

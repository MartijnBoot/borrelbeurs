"""AC32 (Phase 8 T9, D-42, PD15): no v1 key has a way into v2.

v1's access keys are free strings in `config/keys.json`, and the `borrelbeurs-v1`
repository published them. v2 keys are `bb_<key_id>_<secret>`, minted by
`issue_key` and stored only as an argon2id hash, so a v1 key cannot log in
(`tests/api/test_v1_keys.py`). This guards the other half: that nothing under
`app/`, `db/` or `scripts/` ever learns to import one.

- No file names `keys.json`.
- No `ADMIN_TOKEN` (v1's shared admin secret; Phase 3 removed it, AC6d).
- A key row is created only by `issue_key` (`app/api/security.py`): `insert(AuthKey)`
  lives in `app/db/keys.py: create_key`, and `create_key`, `set_secret_hash` and
  `hash_secret` are called only inside `issue_key` -- and `hash_secret` also by
  `dummy_hash`, which builds a hash no secret matches and stores nothing.

Read by AST, like the other meta guards; nothing is imported or run.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("app", "db", "scripts")
SECURITY = Path("app") / "api" / "security.py"
KEYS_REPO = Path("app") / "db" / "keys.py"

# Function -> the (file, enclosing function) pairs allowed to call it.
ALLOWED_CALLERS: dict[str, frozenset[tuple[Path, str]]] = {
    "create_key": frozenset({(SECURITY, "issue_key")}),
    "set_secret_hash": frozenset({(SECURITY, "issue_key")}),
    "hash_secret": frozenset({(SECURITY, "issue_key"), (SECURITY, "dummy_hash")}),
}
INSERT_ALLOWED = frozenset({(KEYS_REPO, "create_key")})


class Finding(NamedTuple):
    path: Path
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail}"


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def find_v1_key_paths(source: str, path: Path) -> list[Finding]:
    """Every way into the key table, or reference to v1's key files, in `source`."""
    found: list[Finding] = []
    if "keys.json" in source:
        line = source[: source.index("keys.json")].count("\n") + 1
        found.append(Finding(path, line, "names `keys.json`, v1's key file"))
    if path.suffix != ".py":
        return found
    tree = ast.parse(source, filename=path.as_posix())

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Name) and node.id == "ADMIN_TOKEN":
            found.append(Finding(path, node.lineno, "`ADMIN_TOKEN`, v1's shared admin secret"))
        if isinstance(node, ast.Call):
            called = _name(node.func)
            if called in ALLOWED_CALLERS and (path, function) not in ALLOWED_CALLERS[called]:
                found.append(Finding(path, node.lineno, f"`{called}(...)` outside `issue_key`"))
            if (
                called == "insert"
                and node.args
                and _name(node.args[0]) == "AuthKey"
                and (path, function) not in INSERT_ALLOWED
            ):
                found.append(Finding(path, node.lineno, "`insert(AuthKey)` outside `create_key`"))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return found


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED:
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if path.suffix in (".py", ".sh", ".cmd", ".ps1") and "__pycache__" not in path.parts:
                files.append(path)
    return files


def test_no_path_from_a_v1_key_into_v2() -> None:
    findings = [
        finding
        for path in _scanned_files()
        for finding in find_v1_key_paths(
            path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT)
        )
    ]

    assert findings == [], "\n".join(map(str, findings))


def test_the_walk_reaches_the_key_code() -> None:
    """Anti-vacuity: the scan sees the files whose calls it allows."""
    seen = {path.relative_to(REPO_ROOT) for path in _scanned_files()}

    assert {SECURITY, KEYS_REPO} <= seen


# --- the detector bites --------------------------------------------------------


def test_a_file_naming_keys_json_is_found(tmp_path: Path) -> None:
    source = 'KEYS = Path("config") / "keys.json"\n'

    (finding,) = find_v1_key_paths(source, Path("app") / "cli" / "import_keys.py")

    assert "keys.json" in finding.detail


def test_admin_token_is_found() -> None:
    (finding,) = find_v1_key_paths("token = ADMIN_TOKEN\n", Path("app") / "x.py")

    assert "ADMIN_TOKEN" in finding.detail


def test_hashing_or_inserting_a_key_outside_issue_key_is_found() -> None:
    source = (
        "async def import_v1(conn, keys):\n"
        "    for key in keys:\n"
        "        await create_key(conn, label=key, role='bar', secret_hash=hash_secret(key))\n"
        "        await conn.execute(insert(AuthKey).values(label=key))\n"
    )

    details = [f.detail for f in find_v1_key_paths(source, Path("app") / "cli" / "v1.py")]

    assert details == [
        "`create_key(...)` outside `issue_key`",
        "`hash_secret(...)` outside `issue_key`",
        "`insert(AuthKey)` outside `create_key`",
    ]


def test_issue_key_itself_is_allowed() -> None:
    source = (
        "async def issue_key(conn, *, role, label):\n"
        "    key_id = await create_key(conn, label=label, role=role, secret_hash='pending')\n"
        "    await set_secret_hash(conn, key_id, hash_secret('s'))\n"
    )

    assert find_v1_key_paths(source, SECURITY) == []

"""Short access keys: the draw, the reading, the hash and login (B-08 T1: AC1, AC2, AC4, AC5).

Pure: `find_login` gets a fake lookup and a counting hasher, nothing touches a
database.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

import argon2
import pytest
from argon2.profiles import RFC_9106_LOW_MEMORY

from app.api import security
from app.api.security import (
    KEY_LENGTH,
    display_key,
    find_login,
    key_hash,
    new_key_symbols,
    normalise_key,
)
from app.db.keys import AuthKeyRow
from app.runtime.crockford import ALPHABET

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 27, tzinfo=UTC)


# --- the draw (AC1) -----------------------------------------------------------------


def test_a_key_is_nine_symbols_of_the_alphabet() -> None:
    keys = [new_key_symbols() for _ in range(200)]

    assert KEY_LENGTH == 9
    assert all(len(key) == 9 and set(key) <= set(ALPHABET) for key in keys)
    assert len(set(keys)) > 195, "random, not derived from anything"
    assert set("".join(keys)) == set(ALPHABET), "every symbol can be drawn"


# --- the reading (SD2: AC2, AC4) --------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    [
        "K7M-4QX-9PR",
        "K7M4QX9PR",
        "k7m4qx9pr",
        "k7m-4qx-9pr",
        "K7M 4QX 9PR",
        " K7M-4QX-9PR\n",
        "K 7 M-4Q X9PR",
    ],
)
def test_a_typed_key_is_read_forgivingly(typed: str) -> None:
    """AC2: any case, without its dashes, spaces anywhere, surrounding whitespace."""
    assert normalise_key(typed) == "K7M4QX9PR"


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("O0O-000-000", "000000000"), ("I1L-il1-111", "111111111")],
)
def test_look_alikes_are_read_as_digits(typed: str, stored: str) -> None:
    """AC2: `O` as `0`, `I` and `L` as `1`."""
    assert normalise_key(typed) == stored


@pytest.mark.parametrize(
    "typed",
    [
        "K7M-4QX-9P",  # 8 symbols
        "K7M-4QX-9PRX",  # 10 symbols
        "K7M-4QX-9PU",  # a U
        "K7M_4QX_9PR",  # an _
        "bb_12_" + "a" * 43,  # a long key
        "K7Q4-M2XD",  # a wallet short code
        "",
    ],
)
def test_anything_else_is_malformed(typed: str) -> None:
    """AC4."""
    assert normalise_key(typed) is None


def test_the_display_form_is_three_groups_of_three() -> None:
    assert display_key("K7M4QX9PR") == "K7M-4QX-9PR"


# --- the hash (SD3, PD2) ------------------------------------------------------------


def test_the_hash_parameters_are_the_ones_password_hasher_used_when_b08_shipped() -> None:
    """A library upgrade that moves these needs a human decision, not a silent follow."""
    pinned = security._KEY_PARAMS

    assert pinned == {
        "time_cost": RFC_9106_LOW_MEMORY.time_cost,
        "memory_cost": RFC_9106_LOW_MEMORY.memory_cost,
        "parallelism": RFC_9106_LOW_MEMORY.parallelism,
        "hash_len": RFC_9106_LOW_MEMORY.hash_len,
        "type": RFC_9106_LOW_MEMORY.type,
    }
    hasher = argon2.PasswordHasher()
    assert (hasher.time_cost, hasher.memory_cost, hasher.parallelism, hasher.hash_len) == (
        RFC_9106_LOW_MEMORY.time_cost,
        RFC_9106_LOW_MEMORY.memory_cost,
        RFC_9106_LOW_MEMORY.parallelism,
        RFC_9106_LOW_MEMORY.hash_len,
    )


def test_a_known_key_has_a_known_hash() -> None:
    """A changed salt or parameter would make every stored key unfindable."""
    assert key_hash("K7M4QX9PR") == (
        "$argon2id$v=19$m=65536,t=3,p=4$x3z3cMfvPBRXJ8QbysJewQ$"
        "HtWnZS7ouB7sI/FGRKXmSpStsIC7/HH1SAJ2W2MPXBI"
    )


def test_equal_symbols_hash_equal_and_different_ones_differ() -> None:
    assert key_hash("K7M4QX9PR") == key_hash("K7M4QX9PR")
    assert key_hash("K7M4QX9PR") != key_hash("K7M4QX9PS")
    assert key_hash("K7M4QX9PR").startswith("$argon2id$")


def test_the_hash_is_the_encoding_password_hasher_writes() -> None:
    """The column has held `PasswordHasher` hashes since Phase 3; the new form verifies too."""
    assert argon2.PasswordHasher().verify(key_hash("K7M4QX9PR"), "K7M4QX9PR")


# --- find_login (SD3: AC4, AC5) -------------------------------------------------------


def _row(symbols: str, *, revoked: bool = False) -> AuthKeyRow:
    return AuthKeyRow(
        key_id=7,
        label="bar 1",
        role="bar",
        secret_hash=f"hash:{symbols}",
        created_at=NOW,
        revoked_at=NOW if revoked else None,
        last_used_at=None,
    )


class CountingHasher:
    """A cheap stand-in for `key_hash` that records which thread ran it."""

    def __init__(self) -> None:
        self.threads: list[int] = []

    def __call__(self, symbols: str) -> str:
        self.threads.append(threading.get_ident())
        return f"hash:{symbols}"


def _run(
    raw: str, rows: dict[str, AuthKeyRow]
) -> tuple[AuthKeyRow | None, list[int], list[str], int]:
    hasher = CountingHasher()
    looked_up: list[str] = []

    async def lookup(secret_hash: str) -> AuthKeyRow | None:
        looked_up.append(secret_hash)
        return rows.get(secret_hash)

    async def scenario() -> tuple[AuthKeyRow | None, int]:
        return await find_login(raw, lookup, hasher=hasher), threading.get_ident()

    found, loop_thread = asyncio.run(scenario())
    return found, hasher.threads, looked_up, loop_thread


@pytest.mark.parametrize(
    "raw", ["", "K7M-4QX-9P", "K7M-4QX-9PRX", "K7M-4QX-9PU", "K7M_4QX_9PR", "bb_1_" + "a" * 43]
)
def test_a_malformed_key_costs_no_hash_and_no_lookup(raw: str) -> None:
    """AC4."""
    found, hashed_on, looked_up, _ = _run(raw, {})

    assert found is None
    assert hashed_on == []
    assert looked_up == []


@pytest.mark.parametrize(
    ("case", "rows", "found"),
    [
        ("unknown", {}, False),
        ("revoked", {"hash:K7M4QX9PR": _row("K7M4QX9PR", revoked=True)}, False),
        ("valid", {"hash:K7M4QX9PR": _row("K7M4QX9PR")}, True),
    ],
)
def test_a_well_formed_key_costs_one_hash_off_the_loop_and_one_lookup(
    case: str, rows: dict[str, AuthKeyRow], found: bool
) -> None:
    """AC5: unknown, revoked and valid alike; only the valid one is found."""
    row, hashed_on, looked_up, loop_thread = _run("k7m 4qx 9pr", rows)

    assert len(hashed_on) == 1, case
    assert hashed_on[0] != loop_thread, f"{case}: the hash ran on the event loop thread"
    assert looked_up == ["hash:K7M4QX9PR"], case
    assert (row is not None) is found, case


# --- provenance (AC1) ---------------------------------------------------------------


def find_non_secrets_randomness(source: str) -> list[str]:
    """Every `random` import or `random.` use, and whether `draw` uses `secrets.choice`."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "random" for a in node.names
        ):
            found.append(f"line {node.lineno}: import random")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "random":
            found.append(f"line {node.lineno}: from random import")
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "random"
        ):
            found.append(f"line {node.lineno}: random.{node.attr}")
    return found


def _draw_uses_secrets_choice(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "draw":
            return any(
                isinstance(call, ast.Attribute)
                and call.attr == "choice"
                and isinstance(call.value, ast.Name)
                and call.value.id == "secrets"
                for call in ast.walk(node)
            )
    return False


@pytest.mark.parametrize("path", ["app/runtime/crockford.py", "app/api/security.py"])
def test_the_minting_path_draws_from_secrets_only(path: str) -> None:
    """AC1."""
    assert find_non_secrets_randomness((REPO_ROOT / path).read_text(encoding="utf-8")) == []


def test_the_draw_uses_secrets_choice() -> None:
    source = (REPO_ROOT / "app" / "runtime" / "crockford.py").read_text(encoding="utf-8")

    assert _draw_uses_secrets_choice(source)


def test_the_scan_finds_a_planted_random() -> None:
    """Anti-vacuity: the scan can fail."""
    planted = (
        "import random\n"
        "from random import choice\n"
        "def draw(length):\n"
        "    return ''.join(random.choice('AB') for _ in range(length))\n"
    )

    assert find_non_secrets_randomness(planted) == [
        "line 1: import random",
        "line 2: from random import",
        "line 4: random.choice",
    ]
    assert not _draw_uses_secrets_choice(planted)

"""Migration 0015: every long key revoked, the hash unique, rollback intact (B-08 T2: AC10-AC13).

On a database of its own at `0014`, two keys are minted the pre-B-08 way and one
is revoked; a session is held for the other. After the upgrade both are revoked,
the session and the long key are refused, the CLI still mints an admin key that
logs in, and the pre-B-08 code path still mints and logs in against the new
schema -- concurrently too. That last part is what keeps `min_code_revision`
"unchanged" honest (SD6).

`_old_mint` and `_old_login` are **frozen** from `main` at `3778ba9`
(`app/api/security.py:77-120`, `:230-251`): the pre-B-08 behaviour as plain SQL
plus `argon2.PasswordHasher()`. They must never follow the live code.
"""

from __future__ import annotations

import asyncio
import secrets
import subprocess
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi.testclient import TestClient
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.api import security
from app.api.deps import SESSION_COOKIE
from app.cli.keys import main
from app.core.config import get_settings
from app.main import create_app
from tests.support.clock import FakeClock

RunAlembic = Callable[..., subprocess.CompletedProcess[str]]

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"


# --- the pre-B-08 key path, frozen (PD8) -------------------------------------------


async def _old_insert(conn: AsyncConnection, role: str, label: str) -> int:
    result = await conn.execute(
        text(
            "INSERT INTO auth_key (label, role, secret_hash) "
            "VALUES (:label, :role, 'pending') RETURNING key_id"
        ),
        {"label": label, "role": role},
    )
    return int(result.scalar_one())


async def _old_finish(conn: AsyncConnection, key_id: int) -> str:
    secret = secrets.token_urlsafe(32)
    await conn.execute(
        text("UPDATE auth_key SET secret_hash = :h WHERE key_id = :k"),
        {"h": PasswordHasher().hash(secret), "k": key_id},
    )
    return f"bb_{key_id}_{secret}"


async def _old_mint(conn: AsyncConnection, role: str, label: str) -> str:
    """`issue_key` before B-08: a placeholder hash, then the real one, in one transaction."""
    return await _old_finish(conn, await _old_insert(conn, role, label))


async def _old_login(conn: AsyncConnection, raw: str) -> bool:
    """`parse_key` then `verify_login` before B-08: by `key_id`, one argon2 verify."""
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "bb" or not parts[1].isdigit():
        return False
    row = (
        await conn.execute(
            text("SELECT secret_hash, revoked_at FROM auth_key WHERE key_id = :k"),
            {"k": int(parts[1])},
        )
    ).one_or_none()
    if row is None:
        return False
    try:
        matched = PasswordHasher().verify(row.secret_hash, parts[2])
    except (VerificationError, InvalidHashError):
        return False
    return bool(matched) and row.revoked_at is None


# --- helpers ---------------------------------------------------------------------


def _on(url: str, body: Callable[[AsyncConnection], Any]) -> Any:
    """`body(conn)` in one committed transaction on a fresh engine."""

    async def scenario() -> Any:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _revoked_at(conn: AsyncConnection) -> dict[int, datetime | None]:
    rows = await conn.execute(text("SELECT key_id, revoked_at FROM auth_key ORDER BY key_id"))
    return {int(row.key_id): row.revoked_at for row in rows}


async def _floor(conn: AsyncConnection) -> str:
    return str(
        (
            await conn.execute(text("SELECT min_code_revision FROM schema_compat WHERE id = 1"))
        ).scalar_one()
    )


@pytest.fixture
def at_0014(
    monkeypatch: pytest.MonkeyPatch, empty_database: str, alembic: RunAlembic
) -> Iterator[str]:
    """`empty_database` at `0014`, and the app's settings pointed at it."""
    step = alembic(empty_database, "upgrade", "0014")
    assert step.returncode == 0, step.stderr
    monkeypatch.setenv("DATABASE_URL", empty_database)
    get_settings.cache_clear()
    yield empty_database
    get_settings.cache_clear()


def _app() -> TestClient:
    return TestClient(
        create_app(clock=FakeClock(T0), run_migrations=False),
        base_url=BASE_URL,
        headers={"origin": BASE_URL},
    )


# --- the switch-over ----------------------------------------------------------------


def test_0015_revokes_every_long_key_and_a_new_admin_key_still_gets_in(
    at_0014: str, alembic: RunAlembic, capsys: pytest.CaptureFixture[str]
) -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, str, int]:
        held = await _old_mint(conn, "admin", "Bestuur")
        gone = await _old_mint(conn, "bar", "Bar 1")
        gone_id = int(gone.split("_")[1])
        await conn.execute(
            text("UPDATE auth_key SET revoked_at = now() - interval '1 day' WHERE key_id = :k"),
            {"k": gone_id},
        )
        return held, gone, gone_id

    held, _, gone_id = _on(at_0014, seed)
    held_id = int(held.split("_")[1])
    before = _on(at_0014, _revoked_at)
    floor_before = _on(at_0014, _floor)
    cookie, _ = security.issue_session(
        held_id, "admin", secret=get_settings().jwt_secret, now_ms=T0
    )

    step = alembic(at_0014, "upgrade", "head")
    assert step.returncode == 0, step.stderr

    # AC10: no row deleted; the unrevoked one now revoked; the revoked one untouched.
    after = _on(at_0014, _revoked_at)
    assert set(after) == {held_id, gone_id}
    assert before[held_id] is None and after[held_id] is not None
    assert after[gone_id] == before[gone_id] is not None

    # AC12: with no unrevoked admin left, the CLI mints one. Minted before the app
    # starts, so the app's own log lines are not in the captured output.
    capsys.readouterr()
    assert main(["create", "--role", "admin", "--label", "Nieuw"]) == 0
    (line,) = capsys.readouterr().out.splitlines()

    with _app() as client:
        # AC11: the held session is refused, and so is the long key itself.
        client.cookies.set(SESSION_COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.clear()
        assert client.post("/api/auth/login", json={"key": held}).status_code == 401

        # AC12: the new admin key logs in.
        assert client.post("/api/auth/login", json={"key": line}).status_code == 200

        # AC10: the list shows both old keys revoked.
        listed = {k["key_id"]: k["revoked"] for k in client.get("/api/keys").json()}
        assert listed[held_id] is True
        assert listed[gone_id] is True

    # AC13: the rollback floor is where it was.
    assert _on(at_0014, _floor) == floor_before


def test_the_pre_b08_mint_and_login_still_work_against_0015(
    at_0014: str, alembic: RunAlembic
) -> None:
    """AC13: a rolled-back image mints and logs in against the new schema."""
    step = alembic(at_0014, "upgrade", "head")
    assert step.returncode == 0, step.stderr

    async def mint(conn: AsyncConnection) -> str:
        return await _old_mint(conn, "admin", "Terug")

    async def login(raw: str) -> bool:
        engine = create_async_engine(at_0014, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                return await _old_login(conn, raw)
        finally:
            await engine.dispose()

    key = _on(at_0014, mint)

    assert asyncio.run(login(key))
    assert not asyncio.run(login(key[:-1] + ("A" if key[-1] != "A" else "B")))


def test_two_concurrent_pre_b08_mints_both_commit_under_the_constraint(
    at_0014: str, alembic: RunAlembic
) -> None:
    """AC13 / R1: the second `'pending'` insert waits for the first transaction, which
    replaces its placeholder before committing, so both mints commit."""
    step = alembic(at_0014, "upgrade", "head")
    assert step.returncode == 0, step.stderr

    async def scenario() -> tuple[bool, str, str, int, bool]:
        engine = create_async_engine(at_0014, poolclass=pool.NullPool)
        try:
            async with engine.connect() as first, engine.connect() as second:
                await first.begin()
                await second.begin()
                first_id = await _old_insert(first, "bar", "Bar A")
                # Started before the first commits: it blocks on the first's 'pending'.
                waiting = asyncio.create_task(_old_insert(second, "bar", "Bar B"))
                done, _ = await asyncio.wait({waiting}, timeout=0.5)
                blocked = waiting not in done
                first_key = await _old_finish(first, first_id)
                await first.commit()
                second_key = await _old_finish(second, await waiting)
                await second.commit()
            async with engine.connect() as conn:
                count = int(
                    (await conn.execute(text("SELECT count(*) FROM auth_key"))).scalar_one()
                )
            async with engine.connect() as conn:
                logged_in = await _old_login(conn, first_key) and await _old_login(conn, second_key)
            return blocked, first_key, second_key, count, logged_in
        finally:
            await engine.dispose()

    blocked, first_key, second_key, count, logged_in = asyncio.run(scenario())

    assert blocked, "the second insert did not wait: the race was not exercised"
    assert first_key != second_key
    assert count == 2, "both mints committed"
    assert logged_in, "both keys log in the pre-B-08 way"


def test_0015_downgrade_drops_the_constraint_and_revives_nothing(
    at_0014: str, alembic: RunAlembic
) -> None:
    """SD6: `downgrade()` undoes the schema change only."""

    async def seed(conn: AsyncConnection) -> None:
        await _old_mint(conn, "admin", "Bestuur")

    _on(at_0014, seed)
    assert alembic(at_0014, "upgrade", "head").returncode == 0
    revoked = _on(at_0014, _revoked_at)

    step = alembic(at_0014, "downgrade", "0014")
    assert step.returncode == 0, step.stderr

    async def same_hash_twice(conn: AsyncConnection) -> None:
        for label in ("A", "B"):
            await conn.execute(
                text("INSERT INTO auth_key (label, role, secret_hash) VALUES (:l, 'bar', 'x')"),
                {"l": label},
            )

    async def revoked_of_the_first(conn: AsyncConnection) -> dict[int, Any]:
        return {k: v for k, v in (await _revoked_at(conn)).items() if k in revoked}

    _on(at_0014, same_hash_twice)
    assert _on(at_0014, revoked_of_the_first) == revoked
    assert all(at is not None for at in revoked.values())

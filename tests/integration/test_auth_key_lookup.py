"""The key repository's hash half: insert on a free hash, find by hash (B-08 T2: SD3; PD5)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db.keys import get_key_by_hash, insert_key, revoke_key
from app.db.models import AuthKey
from app.db.session import create_engine


def _in_transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[Any]]
) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _count(conn: AsyncConnection) -> int:
    return int((await conn.execute(select(func.count()).select_from(AuthKey))).scalar_one())


def test_a_taken_hash_inserts_nothing_even_when_its_row_is_revoked(
    settings: Settings, database_url: str
) -> None:
    async def body(conn: AsyncConnection) -> tuple[int | None, int | None, int | None, int]:
        first = await insert_key(conn, label="Bar 1", role="bar", secret_hash="h1")
        assert first is not None
        again = await insert_key(conn, label="Bar 2", role="bar", secret_hash="h1")
        await revoke_key(conn, first)
        after_revoke = await insert_key(conn, label="Bar 3", role="admin", secret_hash="h1")
        return first, again, after_revoke, await _count(conn)

    first, again, after_revoke, count = _in_transaction(settings, database_url, body)

    assert isinstance(first, int)
    assert again is None
    assert after_revoke is None
    assert count == 1


def test_get_key_by_hash_finds_a_revoked_row_and_nothing_for_an_unknown_hash(
    settings: Settings, database_url: str
) -> None:
    async def body(conn: AsyncConnection) -> tuple[Any, Any, int]:
        key_id = await insert_key(conn, label="Beamer", role="display", secret_hash="h2")
        assert key_id is not None
        await revoke_key(conn, key_id)
        return (
            await get_key_by_hash(conn, "h2"),
            await get_key_by_hash(conn, "no such hash"),
            key_id,
        )

    found, unknown, key_id = _in_transaction(settings, database_url, body)

    assert found is not None
    assert (found.key_id, found.label, found.role, found.revoked) == (
        key_id,
        "Beamer",
        "display",
        True,
    )
    assert unknown is None

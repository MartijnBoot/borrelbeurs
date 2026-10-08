"""The theme repository (Phase 4 T2: SD5; AC8 stored half, AC9 no row; PD4)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db.session import create_engine
from app.db.theme import ThemeRow, get_theme, set_theme
from app.runtime.theme import TOKEN_NAMES, CustomTheme

T = TypeVar("T")


def _transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_an_empty_table_has_no_theme(settings: Settings, database_url: str) -> None:
    """AC9: no row, so the caller falls back to Blauw at revision 0."""
    assert _transaction(settings, database_url, get_theme) is None


def test_the_first_write_is_revision_1_and_each_write_adds_one(
    settings: Settings, database_url: str
) -> None:
    first = _transaction(settings, database_url, lambda conn: set_theme(conn, "rood"))
    second = _transaction(settings, database_url, lambda conn: set_theme(conn, "oudgeld"))
    stored = _transaction(settings, database_url, get_theme)

    assert (first.preset, first.revision) == ("rood", 1)
    assert (second.preset, second.revision) == ("oudgeld", 2)
    assert isinstance(stored, ThemeRow)
    assert (stored.preset, stored.revision) == ("oudgeld", 2)
    assert stored.updated_at >= first.updated_at


def test_writing_the_same_preset_still_bumps_the_revision(
    settings: Settings, database_url: str
) -> None:
    _transaction(settings, database_url, lambda conn: set_theme(conn, "groen"))
    again = _transaction(settings, database_url, lambda conn: set_theme(conn, "groen"))

    assert again.revision == 2


def test_an_unknown_preset_is_refused_and_the_stored_row_is_unchanged(
    settings: Settings, database_url: str
) -> None:
    """AC8 (stored half): the CHECK refuses what the API's validation would."""
    _transaction(settings, database_url, lambda conn: set_theme(conn, "paars"))

    with pytest.raises(IntegrityError, match="theme_preset_check"):
        _transaction(settings, database_url, lambda conn: set_theme(conn, "eigen"))  # type: ignore[arg-type]

    stored = _transaction(settings, database_url, get_theme)
    assert stored is not None
    assert (stored.preset, stored.revision) == ("paars", 1)


def test_a_rolled_back_write_leaves_no_trace(settings: Settings, database_url: str) -> None:
    """The caller owns the transaction: the repository never commits."""

    async def write_then_fail(conn: AsyncConnection) -> None:
        await set_theme(conn, "rood")
        raise RuntimeError("caller aborts")

    with pytest.raises(RuntimeError):
        _transaction(settings, database_url, write_then_fail)

    assert _transaction(settings, database_url, get_theme) is None


def test_a_second_row_is_refused(settings: Settings, database_url: str) -> None:
    """PD4: a single row is a database fact, not a convention."""

    async def second(conn: AsyncConnection) -> None:
        await set_theme(conn, "blauw")
        await conn.execute(text("INSERT INTO theme (id, preset, revision) VALUES (2, 'rood', 1)"))

    with pytest.raises(IntegrityError, match="theme_id_check"):
        _transaction(settings, database_url, second)


def test_a_custom_theme_stores_its_tokens_and_font(settings: Settings, database_url: str) -> None:
    """Phase 6 SD28: `custom_tokens` keyed by token name, `custom_font`."""
    tokens = {name: "#abcdef" for name in TOKEN_NAMES}

    async def body(conn: AsyncConnection) -> ThemeRow | None:
        await set_theme(conn, "custom", custom=CustomTheme(tokens=tokens, font="inter"))
        await set_theme(conn, "rood")
        return await get_theme(conn)

    row = _transaction(settings, database_url, body)

    assert row is not None and row.preset == "rood" and row.revision == 2
    assert row.custom == CustomTheme(tokens=tokens, font="inter")

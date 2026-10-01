"""The news repository (T9).

AC16 (create path); SD13.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.news import NewsItem, create_news, list_news
from app.db.runs import create_draft_run
from app.db.session import create_engine
from exchange import Params


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


def test_news_is_stored_lowercase_and_listed_in_time_order(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(conn, params=Params(), run_seed=1)
                other = await create_draft_run(conn, params=Params(), run_seed=2)
                late = await create_news(conn, run_id, ts_ms=300, level="danger", text="Op!")
                first = await create_news(conn, run_id, ts_ms=100, level="info", text="Open")
                tie = await create_news(conn, run_id, ts_ms=300, level="success", text="Tie")
                gone = await create_news(conn, run_id, ts_ms=200, level="warning", text="x")
                await create_news(conn, other, ts_ms=150, level="info", text="Elders")
                await conn.execute(
                    text("UPDATE news SET deleted_at = now() WHERE news_id = :n"), {"n": gone}
                )
                stored: list[str] = list(
                    (await conn.execute(text("SELECT level FROM news"))).scalars().all()
                )

            async with engine.connect() as conn:
                items = await list_news(conn, run_id)

            assert sorted(stored) == ["danger", "info", "info", "success", "warning"]
            assert items == (
                NewsItem(news_id=first, ts_ms=100, level="info", text="Open"),
                NewsItem(news_id=late, ts_ms=300, level="danger", text="Op!"),
                NewsItem(news_id=tie, ts_ms=300, level="success", text="Tie"),
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("level", ["Danger", "INFO", "notice", ""])
def test_a_level_outside_the_four_raises_before_any_sql(
    settings: Settings, database_url: str, level: str
) -> None:
    """AC16, SD13: `"Danger"` is rejected in Python, not by the CHECK."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(conn, params=Params(), run_seed=1)
                event.listen(engine.sync_engine, "before_cursor_execute", count)
                with pytest.raises(ValueError, match="level"):
                    await create_news(conn, run_id, ts_ms=1, level=level, text="x")  # type: ignore[arg-type]
                event.remove(engine.sync_engine, "before_cursor_execute", count)
            assert statements == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_an_empty_run_has_no_news(settings: Settings, database_url: str) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(conn, params=Params(), run_seed=1)
                assert await list_news(conn, run_id) == ()
        finally:
            await engine.dispose()

    asyncio.run(scenario())

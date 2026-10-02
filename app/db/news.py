"""The news repository: create and list a run's ticker items.

A level outside the four lowercase values of SD13 raises `ValueError` before
any SQL; the `news_level_check` constraint is the second line, not the first.
Updating and deleting news are Phase 3 and 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import News

NewsLevel = Literal["info", "success", "warning", "danger"]
NEWS_LEVELS: tuple[NewsLevel, ...] = get_args(NewsLevel)


@dataclass(frozen=True)
class NewsItem:
    news_id: int
    ts_ms: int
    level: NewsLevel
    text: str


async def create_news(
    conn: AsyncConnection, run_id: int, *, ts_ms: int, level: NewsLevel, text: str
) -> int:
    if level not in NEWS_LEVELS:
        raise ValueError(f"unknown news level {level!r}; expected one of {', '.join(NEWS_LEVELS)}")
    result = await conn.execute(
        insert(News)
        .values(run_id=run_id, ts_ms=ts_ms, level=level, text=text)
        .returning(News.news_id)
    )
    return int(result.scalar_one())


async def list_news(
    conn: AsyncConnection, run_id: int, *, newest_first: bool = False, limit: int | None = None
) -> tuple[NewsItem, ...]:
    """The run's items that are not deleted, by `ts_ms` then `news_id`.

    Oldest first by default, as Phase 2's callers (rehydrate, the import) read
    them; `newest_first` for the API (Phase 3 SD26). `limit` keeps the first n
    in that order.
    """
    order = (News.ts_ms.desc(), News.news_id.desc()) if newest_first else (News.ts_ms, News.news_id)
    statement = (
        select(News.news_id, News.ts_ms, News.level, News.text)
        .where(News.run_id == run_id, News.deleted_at.is_(None))
        .order_by(*order)
    )
    if limit is not None:
        statement = statement.limit(limit)
    result = await conn.execute(statement)
    return tuple(NewsItem(**row._asdict()) for row in result)


async def soft_delete_news(conn: AsyncConnection, run_id: int, news_id: int) -> NewsItem | None:
    """Set `deleted_at` on a live item of the run; the item, or `None` if absent or deleted."""
    result = await conn.execute(
        update(News)
        .where(News.run_id == run_id, News.news_id == news_id, News.deleted_at.is_(None))
        .values(deleted_at=func.now())
        .returning(News.news_id, News.ts_ms, News.level, News.text)
    )
    row = result.one_or_none()
    return None if row is None else NewsItem(**row._asdict())

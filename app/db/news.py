"""The news repository: create and list a run's ticker items.

A level outside the four lowercase values of SD13 raises `ValueError` before
any SQL; the `news_level_check` constraint is the second line, not the first.
Updating and deleting news are Phase 3 and 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from sqlalchemy import insert, select
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


async def list_news(conn: AsyncConnection, run_id: int) -> tuple[NewsItem, ...]:
    """The run's items that are not deleted, by `ts_ms`, then `news_id`."""
    result = await conn.execute(
        select(News.news_id, News.ts_ms, News.level, News.text)
        .where(News.run_id == run_id, News.deleted_at.is_(None))
        .order_by(News.ts_ms, News.news_id)
    )
    return tuple(NewsItem(**row._asdict()) for row in result)

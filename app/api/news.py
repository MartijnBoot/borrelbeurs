"""News: list, post and delete ticker items (Phase 3 SD1, SD26; AC28).

`GET` lists the live run's items that are not deleted, newest first, from
holder memory. `POST {level, text}` takes one of the four lowercase levels only
(SD26: unlike the v1 import, the API does not fold case) and text trimmed to
1-500 characters; `DELETE` soft-deletes, 404 `news_not_found` if absent or
already deleted. Each change is one `holder.mutate("news", ...)` -- one
transaction, published after commit -- and is broadcast as `news {op, item}`.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.api.deps import ALL_ROLES, Principal, clock_of, refuse_while_draining, require_role
from app.core.errors import AppError
from app.db.news import NewsItem, NewsLevel, create_news, soft_delete_news
from app.realtime.messages import NewsItemData
from app.runtime.holder import MarketHolder, MarketView, NewsChanged, Outcome

router = APIRouter(prefix="/news", tags=["news"])


class NewsNotFound(AppError):
    status_code = 404
    code = "news_not_found"


class NewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: NewsLevel
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _data(item: NewsItem) -> NewsItemData:
    return NewsItemData(news_id=item.news_id, ts_ms=item.ts_ms, level=item.level, text=item.text)


def _holder(request: Request) -> MarketHolder:
    holder: MarketHolder = request.app.state.holder
    return holder


@router.get("")
async def list_items(
    request: Request, _: Annotated[Principal, Depends(require_role(*ALL_ROLES))]
) -> list[NewsItemData]:
    return [_data(item) for item in reversed(_holder(request).news)]


@router.post("", status_code=201)
async def add_item(
    body: NewsRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("bar", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> NewsItemData:
    holder = _holder(request)
    clock = clock_of(request)

    async def step(view: MarketView) -> Outcome[NewsItem]:
        assert view.run_id is not None and view.state is not None
        ts_ms = clock.wall_ms()
        async with holder.engine.begin() as conn:
            news_id = await create_news(
                conn, view.run_id, ts_ms=ts_ms, level=body.level, text=body.text
            )
        item = NewsItem(news_id=news_id, ts_ms=ts_ms, level=body.level, text=body.text)
        return Outcome(
            result=item,
            view=dataclasses.replace(view, news=(*view.news, item)),
            events=(
                NewsChanged(run_id=view.run_id, version=view.state.version, op="add", item=item),
            ),
        )

    return _data(await holder.mutate("news", step))


@router.delete("/{news_id}")
async def delete_item(
    news_id: int,
    request: Request,
    _: Annotated[Principal, Depends(require_role("bar", "admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> NewsItemData:
    holder = _holder(request)

    async def step(view: MarketView) -> Outcome[NewsItem]:
        assert view.run_id is not None and view.state is not None
        async with holder.engine.begin() as conn:
            item = await soft_delete_news(conn, view.run_id, news_id)
        if item is None:
            raise NewsNotFound(f"no news item {news_id}")
        return Outcome(
            result=item,
            view=dataclasses.replace(
                view, news=tuple(n for n in view.news if n.news_id != news_id)
            ),
            events=(
                NewsChanged(run_id=view.run_id, version=view.state.version, op="delete", item=item),
            ),
        )

    return _data(await holder.mutate("news", step))

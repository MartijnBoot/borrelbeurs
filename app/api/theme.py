"""The theme over HTTP: `GET /theme.css` and `PUT /api/theme` (Phase 4 SD5, SD8, SD9; PD5).

**`/theme.css` is public (SD8):** the login page must paint themed too, and the
tokens are not secret. It renders `app.state.theme` -- loaded at boot, replaced
after each write (PD5) -- with `Cache-Control: no-cache` and an ETag from the
revision, so a reload revalidates cheaply. `index.html` links it as a blocking
stylesheet before any script (ADR 0005).

**`PUT /api/theme {preset}`** is admin-only and takes one of the five presets.
It never touches `MarketHolder`: `mutate` refuses with no live run, and SD9
forbids the engine state lock for theme writes. So it commits in its own
transaction, replaces `app.state.theme` only if the committed revision is higher
(two racing writes converge on the last one), and broadcasts `theme` straight on
the hub, which takes the next `seq` with or without a run.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import Principal, clock_of, require_role
from app.db.theme import set_theme
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, ThemeData, theme_data
from app.runtime.holder import MarketHolder
from app.runtime.theme import PresetName, Theme, render_css, resolve

theme_css_router = APIRouter(tags=["theme"])
theme_router = APIRouter(prefix="/theme", tags=["theme"])


class ThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: PresetName


@theme_css_router.get("/theme.css", response_class=Response)
async def theme_css(request: Request) -> Response:
    theme: Theme = request.app.state.theme
    etag = f'"theme-{theme.revision}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(render_css(theme), media_type="text/css", headers=headers)


@theme_router.put("")
async def put_theme(
    body: ThemeRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
) -> ThemeData:
    state = request.app.state
    async with state.engine.begin() as conn:
        row = await set_theme(conn, body.preset)
    theme = resolve(row.preset, row.revision)
    if theme.revision > state.theme.revision:
        state.theme = theme
    data = theme_data(theme)
    holder: MarketHolder = state.holder
    hub: Hub = state.hub
    hub.broadcast(
        Envelope(
            type="theme",
            seq=0,  # the hub stamps the real one
            ts_ms=clock_of(request).wall_ms(),
            run_id=holder.run_id,
            version=None,
            data=data,
        )
    )
    return data

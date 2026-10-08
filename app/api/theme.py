"""The theme over HTTP: `GET /theme.css` and `PUT /api/theme` (Phase 4 SD5, SD8, SD9; PD5).

**`/theme.css` is public (SD8):** the login page must paint themed too, and the
tokens are not secret. It renders `app.state.theme` -- loaded at boot, replaced
after each write (PD5) -- with `Cache-Control: no-cache` and an ETag from the
revision and the preset, so a reload revalidates cheaply. The preset is in it
because revisions restart at 1 when the `theme` table is recreated (a fresh
database, a migration round trip, the cutover): a revision alone would 304 a
browser's cached preset over a different one. `index.html` links it as a blocking
stylesheet before any script (ADR 0005).

**`PUT /api/theme {preset, tokens?, font?}`** is admin-only and takes one of the
five presets, or `custom` (Phase 6 SD28, PD8). `tokens` -- exactly the manifest's,
each a hex colour -- and `font` come only with `custom`, and only together;
`custom` alone reuses the stored custom theme, or is 409 `no_custom_theme`.
It never touches `MarketHolder`: `mutate` refuses with no live run, and SD9
forbids the engine state lock for theme writes. So it commits in its own
transaction, replaces `app.state.theme` only if the committed revision is higher
(two racing writes converge on the last one), and broadcasts `theme` straight on
the hub, which takes the next `seq` with or without a run.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from app.api.deps import Principal, clock_of, refuse_while_draining, require_role
from app.core.errors import AppError
from app.db.theme import get_theme, set_theme
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, ThemeData, theme_data
from app.runtime.holder import MarketHolder
from app.runtime.theme import (
    HEX,
    TOKEN_NAMES,
    CustomTheme,
    FontName,
    PresetName,
    Theme,
    render_css,
    resolve,
)

theme_css_router = APIRouter(tags=["theme"])
theme_router = APIRouter(prefix="/theme", tags=["theme"])


HexColour = Annotated[str, StringConstraints(pattern=HEX.pattern)]


class NoCustomTheme(AppError):
    status_code = 409
    code = "no_custom_theme"


class ThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: PresetName
    tokens: dict[str, HexColour] | None = None
    font: FontName | None = None

    @field_validator("tokens")
    @classmethod
    def _exactly_the_manifest(cls, tokens: dict[str, str] | None) -> dict[str, str] | None:
        if tokens is not None and set(tokens) != set(TOKEN_NAMES):
            missing = sorted(set(TOKEN_NAMES) - set(tokens))
            extra = sorted(set(tokens) - set(TOKEN_NAMES))
            raise ValueError(f"tokens must be the manifest's: missing {missing}, extra {extra}")
        return tokens

    @model_validator(mode="after")
    def _custom_only_and_together(self) -> ThemeRequest:
        given = (self.tokens is not None, self.font is not None)
        if any(given) and self.preset != "custom":
            raise ValueError("tokens and font come only with preset 'custom'")
        if given[0] != given[1]:
            raise ValueError("tokens and font come together")
        return self


@theme_css_router.get("/theme.css", response_class=Response)
async def theme_css(request: Request) -> Response:
    theme: Theme = request.app.state.theme
    etag = f'"theme-{theme.revision}-{theme.preset}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(render_css(theme), media_type="text/css", headers=headers)


@theme_router.put("")
async def put_theme(
    body: ThemeRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> ThemeData:
    state = request.app.state
    custom = (
        None
        if body.tokens is None or body.font is None
        else CustomTheme(tokens=body.tokens, font=body.font)
    )
    async with state.engine.begin() as conn:
        if body.preset == "custom" and custom is None:
            stored = await get_theme(conn)
            if stored is None or stored.custom is None:
                raise NoCustomTheme("no custom theme is stored; send its tokens and font")
            # Re-sent: the upsert's proposed row is checked against `theme_custom_check`
            # even when it only updates.
            custom = stored.custom
        row = await set_theme(conn, body.preset, custom=custom)
    theme = resolve(row.preset, row.revision, custom=row.custom)
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

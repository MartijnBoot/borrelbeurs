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

**`POST /api/theme/images/{slot}`** (Phase 6 SD29; AC31, AC33, AC34) takes
multipart `file`. A `Content-Length` past the limit is 413 `too_large` before
any read; otherwise the request stream passes through `read_limited` before it
reaches the multipart parser, which caps nothing itself, so a body past the
limit is refused within one chunk of it. The image is typed by `sniff` alone,
else 415 `unsupported_media_type`. One transaction stores the asset, points the
slot at it, deletes the slot's previous asset and bumps the revision; the theme
is then broadcast as `PUT` does. **`DELETE /api/theme/images/{slot}`** clears
the slot and deletes its asset the same way; an empty slot changes nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.deps import Principal, clock_of, refuse_while_draining, require_role
from app.core.errors import AppError
from app.db.assets import delete_asset, insert_asset
from app.db.theme import ThemeRow, get_image, get_theme, set_image, set_theme
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, ThemeData, theme_data
from app.runtime.holder import MarketHolder
from app.runtime.images import (
    MAX_IMAGE_BYTES,
    TooLarge,
    UnsupportedMediaType,
    read_limited,
    sniff,
)
from app.runtime.theme import (
    HEX,
    TOKEN_NAMES,
    CustomTheme,
    FontName,
    ImageSlot,
    PresetName,
    Theme,
    render_css,
    resolve,
)

theme_css_router = APIRouter(tags=["theme"])
theme_router = APIRouter(prefix="/theme", tags=["theme"])


# Room for the multipart boundary and part headers around a full-size image; the
# reader stops within one chunk of this, the image itself is held to 5 MB after.
_BODY_LIMIT = MAX_IMAGE_BYTES + 16 * 1024

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
    return _publish(request, row)


class ImageData(BaseModel):
    """A slot write's result: the slot's asset now (`None` once removed) and the revision."""

    asset_id: int | None
    revision: int


class InvalidUpload(AppError):
    status_code = 422
    code = "invalid_request"


def _publish(request: Request, row: ThemeRow) -> ThemeData:
    """Adopt a committed theme row if it is newer, and broadcast it (SD9)."""
    state = request.app.state
    theme = resolve(row.preset, row.revision, custom=row.custom, images=row.images)
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


async def _read_file(request: Request) -> bytes:
    """The multipart `file` part, read through `read_limited` before the parser (AC33)."""
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > _BODY_LIMIT:
        raise TooLarge(f"the upload is larger than {MAX_IMAGE_BYTES} bytes")
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise _no_file("send the image as multipart/form-data")
    parser = MultiPartParser(
        request.headers, read_limited(request.stream(), _BODY_LIMIT), max_files=1, max_fields=0
    )
    try:
        form = await parser.parse()
    except MultiPartException as error:
        raise _no_file(error.message) from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise _no_file("the form has no file field 'file'")
        data = await upload.read()
    finally:
        await form.close()
    if len(data) > MAX_IMAGE_BYTES:
        raise TooLarge(f"the image is larger than {MAX_IMAGE_BYTES} bytes")
    return data


def _no_file(message: str) -> InvalidUpload:
    return InvalidUpload(message, extra={"faults": [{"loc": ["body", "file"], "msg": message}]})


@theme_router.post("/images/{slot}", status_code=201)
async def post_image(
    slot: ImageSlot,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> ImageData:
    data = await _read_file(request)
    content_type = sniff(data[:16])
    if content_type is None:
        raise UnsupportedMediaType("only PNG, JPEG, WebP and GIF images are accepted")
    async with request.app.state.engine.begin() as conn:
        asset_id = await insert_asset(conn, content_type=content_type, data=data)
        row, replaced = await set_image(conn, slot, asset_id)
        if replaced is not None:
            await delete_asset(conn, replaced)
    _publish(request, row)
    return ImageData(asset_id=asset_id, revision=row.revision)


@theme_router.delete("/images/{slot}")
async def delete_image(
    slot: ImageSlot,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> ImageData:
    async with request.app.state.engine.begin() as conn:
        if await get_image(conn, slot) is None:
            return ImageData(asset_id=None, revision=request.app.state.theme.revision)
        row, replaced = await set_image(conn, slot, None)
        if replaced is not None:
            await delete_asset(conn, replaced)
    _publish(request, row)
    return ImageData(asset_id=None, revision=row.revision)

"""`GET /assets/{asset_id}`: an uploaded image, public (Phase 6 SD29; AC32; PD10).

Public like `/theme.css`: the board and the login page paint with these. The
response carries the stored content type, `nosniff` and `default-src 'none'`,
so a browser never runs or re-types it, and caches it for a year: an
`asset_id` is never reused. An unknown id is 404.

The path uses Starlette's `int` converter, so Vite's hashed `/assets/index-*.js`
matches no route here and falls through to the SPA mount (PD10).
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Request, Response

from app.api.deps import db_engine
from app.core.errors import AppError
from app.db.assets import get_asset

router = APIRouter(tags=["assets"])

_HEADERS: Final = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    "Cache-Control": "public, max-age=31536000, immutable",
}


class AssetNotFound(AppError):
    status_code = 404
    code = "asset_not_found"


@router.get("/assets/{asset_id:int}", response_class=Response)
async def get_asset_bytes(asset_id: int, request: Request) -> Response:
    async with db_engine(request).connect() as conn:
        asset = await get_asset(conn, asset_id)
    if asset is None:
        raise AssetNotFound(f"no asset {asset_id}")
    return Response(asset.data, media_type=asset.content_type, headers=_HEADERS)

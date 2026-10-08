"""The `asset` repository (Phase 6 SD29).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/theme.py`. An asset is referenced by
exactly one theme slot; the slot's writer deletes the one it replaces (AC34).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Asset
from app.runtime.images import ContentType


@dataclass(frozen=True)
class StoredAsset:
    content_type: str
    data: bytes


async def insert_asset(conn: AsyncConnection, *, content_type: ContentType, data: bytes) -> int:
    result = await conn.execute(
        insert(Asset)
        .values(
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
            data=data,
            bytes=len(data),
        )
        .returning(Asset.asset_id)
    )
    return int(result.scalar_one())


async def get_asset(conn: AsyncConnection, asset_id: int) -> StoredAsset | None:
    row = (
        await conn.execute(select(Asset.content_type, Asset.data).where(Asset.asset_id == asset_id))
    ).one_or_none()
    return None if row is None else StoredAsset(row.content_type, bytes(row.data))


async def delete_asset(conn: AsyncConnection, asset_id: int) -> None:
    await conn.execute(delete(Asset).where(Asset.asset_id == asset_id))

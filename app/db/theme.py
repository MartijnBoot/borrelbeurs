"""The `theme` repository (Phase 4 SD5, plan PD4).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/keys.py`. The table holds at most
one row; `get_theme` returning `None` means "Blauw at revision 0" to the caller.

The custom theme (Phase 6 SD28) is `custom_tokens`, an object keyed by token
name, and `custom_font`; a write without one keeps the stored one.

The four image slots (Phase 6 SD29) are one `asset` pointer each. `set_image`
points a slot and returns the pointer it replaced, for the caller to delete in
the same transaction (AC34).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import Row, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Theme
from app.runtime.theme import DEFAULT_PRESET, CustomTheme, FontName, ImageSlot, PresetName

_SLOT_COLUMNS: Final = {
    "bg": Theme.bg_asset_id,
    "header": Theme.header_asset_id,
    "logo": Theme.logo_asset_id,
    "promo": Theme.promo_asset_id,
}


@dataclass(frozen=True)
class ThemeRow:
    preset: PresetName
    revision: int
    updated_at: datetime
    custom: CustomTheme | None = None
    # Each image slot's asset id, or None (Phase 6 SD29).
    images: Mapping[ImageSlot, int | None] = field(default_factory=dict)


_COLUMNS = (
    Theme.preset,
    Theme.revision,
    Theme.updated_at,
    Theme.custom_tokens,
    Theme.custom_font,
    Theme.bg_asset_id,
    Theme.header_asset_id,
    Theme.logo_asset_id,
    Theme.promo_asset_id,
)


def _row(row: Row[Any]) -> ThemeRow:
    # The CHECK constraints hold `preset` to `PresetName` and `custom_font` to `FontName`.
    custom = (
        None
        if row.custom_tokens is None or row.custom_font is None
        else CustomTheme(tokens=row.custom_tokens, font=cast(FontName, row.custom_font))
    )
    images: dict[ImageSlot, int | None] = {
        "bg": row.bg_asset_id,
        "header": row.header_asset_id,
        "logo": row.logo_asset_id,
        "promo": row.promo_asset_id,
    }
    return ThemeRow(cast(PresetName, row.preset), row.revision, row.updated_at, custom, images)


async def get_theme(conn: AsyncConnection) -> ThemeRow | None:
    row = (await conn.execute(select(*_COLUMNS))).one_or_none()
    return None if row is None else _row(row)


async def set_theme(
    conn: AsyncConnection, preset: PresetName, *, custom: CustomTheme | None = None
) -> ThemeRow:
    """Store `preset`, and `custom` if given: revision 1 on the first write, one more after.

    One `INSERT ... ON CONFLICT DO UPDATE`, so two racing writes serialise on the
    row and each gets its own revision. `preset == "custom"` with no custom theme
    stored or given violates `theme_custom_check`.
    """
    values: dict[str, object] = {"preset": preset, "revision": 1}
    if custom is not None:
        values |= {"custom_tokens": dict(custom.tokens), "custom_font": custom.font}
    statement = insert(Theme).values(**values)
    updates: dict[str, object] = {
        "preset": statement.excluded.preset,
        "revision": Theme.revision + 1,
        "updated_at": func.now(),
    }
    if custom is not None:
        updates |= {
            "custom_tokens": statement.excluded.custom_tokens,
            "custom_font": statement.excluded.custom_font,
        }
    upsert = statement.on_conflict_do_update(index_elements=[Theme.id], set_=updates).returning(
        *_COLUMNS
    )
    return _row((await conn.execute(upsert)).one())


async def set_image(
    conn: AsyncConnection, slot: ImageSlot, asset_id: int | None
) -> tuple[ThemeRow, int | None]:
    """Point `slot` at `asset_id` (or nothing) and bump the revision; the row and the old pointer.

    With no theme row yet, the first write inserts Blauw at revision 1. Otherwise
    the row is locked first, so the pointer read is the one this write replaces.
    """
    column = _SLOT_COLUMNS[slot]
    inserted = (
        await conn.execute(
            insert(Theme)
            .values(preset=DEFAULT_PRESET, revision=1, **{column.key: asset_id})
            .on_conflict_do_nothing(index_elements=[Theme.id])
            .returning(*_COLUMNS)
        )
    ).one_or_none()
    if inserted is not None:
        return _row(inserted), None
    old = (await conn.execute(select(column).with_for_update())).scalar_one()
    row = (
        await conn.execute(
            update(Theme)
            .values(
                {column: asset_id, Theme.revision: Theme.revision + 1, Theme.updated_at: func.now()}
            )
            .returning(*_COLUMNS)
        )
    ).one()
    return _row(row), None if old is None else int(old)


async def get_image(conn: AsyncConnection, slot: ImageSlot) -> int | None:
    """The asset `slot` points at, if any."""
    value = (await conn.execute(select(_SLOT_COLUMNS[slot]))).scalar_one_or_none()
    return None if value is None else int(value)

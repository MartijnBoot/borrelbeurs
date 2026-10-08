"""The `theme` repository (Phase 4 SD5, plan PD4).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/keys.py`. The table holds at most
one row; `get_theme` returning `None` means "Blauw at revision 0" to the caller.

The custom theme (Phase 6 SD28) is `custom_tokens`, an object keyed by token
name, and `custom_font`; a write without one keeps the stored one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Row, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Theme
from app.runtime.theme import CustomTheme, FontName, PresetName


@dataclass(frozen=True)
class ThemeRow:
    preset: PresetName
    revision: int
    updated_at: datetime
    custom: CustomTheme | None = None


_COLUMNS = (Theme.preset, Theme.revision, Theme.updated_at, Theme.custom_tokens, Theme.custom_font)


def _row(row: Row[Any]) -> ThemeRow:
    # The CHECK constraints hold `preset` to `PresetName` and `custom_font` to `FontName`.
    custom = (
        None
        if row.custom_tokens is None or row.custom_font is None
        else CustomTheme(tokens=row.custom_tokens, font=cast(FontName, row.custom_font))
    )
    return ThemeRow(cast(PresetName, row.preset), row.revision, row.updated_at, custom)


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

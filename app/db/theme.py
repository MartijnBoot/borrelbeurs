"""The `theme` repository (Phase 4 SD5, plan PD4).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/keys.py`. The table holds at most
one row; `get_theme` returning `None` means "Blauw at revision 0" to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Theme
from app.runtime.theme import PresetName


@dataclass(frozen=True)
class ThemeRow:
    preset: PresetName
    revision: int
    updated_at: datetime


_COLUMNS = (Theme.preset, Theme.revision, Theme.updated_at)


def _row(preset: str, revision: int, updated_at: datetime) -> ThemeRow:
    # The CHECK constraint holds `preset` to the five names `PresetName` lists.
    return ThemeRow(cast(PresetName, preset), revision, updated_at)


async def get_theme(conn: AsyncConnection) -> ThemeRow | None:
    row = (await conn.execute(select(*_COLUMNS))).one_or_none()
    return None if row is None else _row(*row)


async def set_theme(conn: AsyncConnection, preset: PresetName) -> ThemeRow:
    """Store `preset`: revision 1 on the first write, one more on each write after.

    One `INSERT ... ON CONFLICT DO UPDATE`, so two racing writes serialise on the
    row and each gets its own revision.
    """
    statement = insert(Theme).values(preset=preset, revision=1)
    upsert = statement.on_conflict_do_update(
        index_elements=[Theme.id],
        set_={
            "preset": statement.excluded.preset,
            "revision": Theme.revision + 1,
            "updated_at": func.now(),
        },
    ).returning(*_COLUMNS)
    preset_, revision, updated_at = (await conn.execute(upsert)).one()
    return _row(preset_, revision, updated_at)

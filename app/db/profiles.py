"""The `settings_profile` repository (B-04 SD5, SD7, SD12, SD15; plan PD4-PD6).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/runs.py`. What `settings` holds and
whether it is within today's rules is the caller's (`app/runtime/config_patch.py`);
this module stores and returns it as it is.

A name is compared trimmed and case-folded (`name_key`, as a drink's), and the
unique index on it decides a race: of two saves of one new name, one inserts and
the other gets `ProfileExists`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.errors import AppError
from app.db.models import SettingsProfile
from app.db.runs import name_key


class ProfileNotFound(AppError):
    """No profile has this id (SD15)."""

    status_code = 404
    code = "profile_not_found"


class ProfileExists(AppError):
    """A profile already has this name, trimmed and case-folded; the error carries its
    `profile_id` (SD5, SD15, as `DraftExists`)."""

    status_code = 409
    code = "profile_exists"


@dataclass(frozen=True)
class ProfileRow:
    profile_id: int
    name: str
    settings: dict[str, Any]
    source_run_name: str
    saved_at: datetime
    saved_by: str


_COLUMNS = (
    SettingsProfile.profile_id,
    SettingsProfile.name,
    SettingsProfile.settings,
    SettingsProfile.source_run_name,
    SettingsProfile.saved_at,
    SettingsProfile.saved_by,
)


def _row(row: Row[Any]) -> ProfileRow:
    return ProfileRow(
        int(row.profile_id),
        row.name,
        dict(row.settings),
        row.source_run_name,
        row.saved_at,
        row.saved_by,
    )


async def list_profiles(conn: AsyncConnection) -> list[ProfileRow]:
    """Every profile, by case-folded name (SD12), sorted here: the collation would differ."""
    rows = (await conn.execute(select(*_COLUMNS, SettingsProfile.name_key))).all()
    return [_row(row) for row in sorted(rows, key=lambda row: (row.name_key, row.profile_id))]


async def get_profile(conn: AsyncConnection, profile_id: int) -> ProfileRow:
    row = (
        await conn.execute(select(*_COLUMNS).where(SettingsProfile.profile_id == profile_id))
    ).one_or_none()
    if row is None:
        raise ProfileNotFound(f"no profile {profile_id}")
    return _row(row)


async def save_profile(
    conn: AsyncConnection,
    *,
    name: str,
    settings: Mapping[str, Any],
    source_run_name: str,
    saved_by: str,
    overwrite: bool,
) -> tuple[ProfileRow, bool]:
    """Store a profile; the row and whether it was created (else overwritten).

    Without `overwrite` an existing name is `ProfileExists`, nothing changed. With
    it, the existing profile's settings, source, author and time are replaced and
    its stored name kept (SD5); a name nobody holds is inserted either way.
    """
    name = name.strip()
    statement = insert(SettingsProfile).values(
        name=name,
        name_key=name_key(name),
        settings=dict(settings),
        source_run_name=source_run_name,
        saved_by=saved_by,
    )
    if overwrite:
        statement = statement.on_conflict_do_update(
            index_elements=[SettingsProfile.name_key],
            set_={
                "settings": statement.excluded.settings,
                "source_run_name": statement.excluded.source_run_name,
                "saved_by": statement.excluded.saved_by,
                "saved_at": func.now(),
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=[SettingsProfile.name_key])
    # `xmax` is 0 on a row this statement inserted, and set on one it updated.
    row = (
        await conn.execute(statement.returning(*_COLUMNS, literal_column("xmax = 0")))
    ).one_or_none()
    if row is None:
        existing = (
            await conn.execute(
                select(SettingsProfile.profile_id).where(SettingsProfile.name_key == name_key(name))
            )
        ).scalar_one()
        raise ProfileExists(f"a profile named {name!r} exists", extra={"profile_id": int(existing)})
    return _row(row), bool(row[-1])


async def delete_profile(conn: AsyncConnection, profile_id: int) -> None:
    deleted = await conn.execute(
        delete(SettingsProfile)
        .where(SettingsProfile.profile_id == profile_id)
        .returning(SettingsProfile.profile_id)
    )
    if deleted.one_or_none() is None:
        raise ProfileNotFound(f"no profile {profile_id}")

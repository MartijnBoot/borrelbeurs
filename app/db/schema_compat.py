"""May this image run against the schema it finds? (Phase 8 SD3, plan PD2.)

Boot asks before it migrates, under the advisory lock:

- **The database's revision is one this image's scripts know** (or there is none
  yet): migrate to head, as ADR 0011 always did.
- **Unknown, but `schema_compat.min_code_revision` is known:** a newer image
  migrated, and declared that code as old as that revision still runs. History is
  linear, so this image's head is at or after it: serve the schema as it is.
- **Unknown, and the floor unknown or missing:** a newer image contracted past
  this one. Refuse to boot, having written nothing.

Read with raw SQL, not the models: the two tables are the contract between images
of different ages, so the read must not depend on this image's idea of them.
"""

from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class DbState:
    db_revision: str | None
    min_code_revision: str | None


class Decision(Enum):
    MIGRATE = "migrate"
    AHEAD = "ahead"
    REFUSE = "refuse"


async def read_db_state(conn: AsyncConnection) -> DbState:
    """`alembic_version` and the `schema_compat` row, either of which may not exist."""
    has_version, has_compat = (
        await conn.execute(
            text(
                "SELECT to_regclass('alembic_version') IS NOT NULL, "
                "to_regclass('schema_compat') IS NOT NULL"
            )
        )
    ).one()
    db_revision = None
    if has_version:
        db_revision = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    min_code_revision = None
    if has_compat:
        min_code_revision = (
            await conn.execute(text("SELECT min_code_revision FROM schema_compat WHERE id = 1"))
        ).scalar_one_or_none()
    return DbState(db_revision=db_revision, min_code_revision=min_code_revision)


def decide(
    known: Container[str], db_revision: str | None, min_code_revision: str | None
) -> Decision:
    """SD3's three cases; `known` is every revision this image's scripts hold."""
    if db_revision is None or db_revision in known:
        return Decision.MIGRATE
    if min_code_revision is not None and min_code_revision in known:
        return Decision.AHEAD
    return Decision.REFUSE

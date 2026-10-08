"""The `auth_key` repository (Phase 3 SD5).

Every function takes an `AsyncConnection` and never begins or commits: the
caller owns the transaction, as in `app/db/runs.py`. Only the argon2id hash of
a key's secret is ever stored (AC6c); hashing and the key format live in
`app/api/security.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import AuthKey

Role = Literal["display", "bar", "admin"]
ROLES: tuple[Role, ...] = ("display", "bar", "admin")


@dataclass(frozen=True)
class AuthKeyRow:
    key_id: int
    label: str
    role: Role
    secret_hash: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


_COLUMNS = (
    AuthKey.key_id,
    AuthKey.label,
    AuthKey.role,
    AuthKey.secret_hash,
    AuthKey.created_at,
    AuthKey.revoked_at,
    AuthKey.last_used_at,
)


async def create_key(conn: AsyncConnection, *, label: str, role: Role, secret_hash: str) -> int:
    result = await conn.execute(
        insert(AuthKey)
        .values(label=label, role=role, secret_hash=secret_hash)
        .returning(AuthKey.key_id)
    )
    return int(result.scalar_one())


async def set_secret_hash(conn: AsyncConnection, key_id: int, secret_hash: str) -> None:
    """Replace a key's hash; `app.cli.keys create` needs the `key_id` before it can hash."""
    result = await conn.execute(
        update(AuthKey)
        .where(AuthKey.key_id == key_id)
        .values(secret_hash=secret_hash)
        .returning(AuthKey.key_id)
    )
    if result.scalar_one_or_none() is None:
        raise LookupError(f"no key {key_id}")


async def get_key(conn: AsyncConnection, key_id: int) -> AuthKeyRow | None:
    row = (await conn.execute(select(*_COLUMNS).where(AuthKey.key_id == key_id))).one_or_none()
    return None if row is None else AuthKeyRow(**row._asdict())


async def list_keys(conn: AsyncConnection) -> list[AuthKeyRow]:
    result = await conn.execute(select(*_COLUMNS).order_by(AuthKey.key_id))
    return [AuthKeyRow(**row._asdict()) for row in result]


async def revoke_key(conn: AsyncConnection, key_id: int) -> None:
    """Set `revoked_at` (kept as first set if already revoked), or `LookupError`."""
    result = await conn.execute(
        update(AuthKey)
        .where(AuthKey.key_id == key_id)
        .values(revoked_at=func.coalesce(AuthKey.revoked_at, func.now()))
        .returning(AuthKey.key_id)
    )
    if result.scalar_one_or_none() is None:
        raise LookupError(f"no key {key_id}")


async def touch_last_used(conn: AsyncConnection, key_id: int) -> None:
    """A successful login's one write to `auth_key` (SD6)."""
    await conn.execute(
        update(AuthKey).where(AuthKey.key_id == key_id).values(last_used_at=func.now())
    )


async def lock_unrevoked_admins(conn: AsyncConnection) -> list[int]:
    """The unrevoked admin keys' ids, each row locked `FOR UPDATE` (Phase 6 SD30).

    Two concurrent revokes of the last two admins serialise here, so neither
    can see the other's admin as still there.
    """
    result = await conn.execute(
        select(AuthKey.key_id)
        .where(AuthKey.role == "admin", AuthKey.revoked_at.is_(None))
        .order_by(AuthKey.key_id)
        .with_for_update()
    )
    return [int(key_id) for key_id in result.scalars()]

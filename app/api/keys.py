"""Access keys over HTTP (Phase 6 SD30; AC36-AC38; PD12).

`GET /api/keys` lists every key: id, label, role, created, last used and
whether it is revoked -- never a secret or a hash. `POST /api/keys {role,
label}` mints one through `issue_key` and returns `{key_id, key}`: the only
time the key exists outside its holder's hands (AC36). `DELETE
/api/keys/{key_id}` revokes it; after the commit, every WebSocket of that key
is closed with 4401 (PD12), and its sessions get 401 on their next request, as
`require_role` reads the key row each time (AC37). Revoking the last unrevoked
admin key is 409 `last_admin_key`, decided under a lock on the admin rows (AC38);
an unknown key is 404 `key_not_found`.

The first admin key stays CLI-only (`app.cli.keys`). Admin only; the writes
refuse while draining (SD24).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.api.deps import Principal, db_engine, refuse_while_draining, require_role
from app.api.security import issue_key, parse_key
from app.core.errors import AppError
from app.db.keys import Role, get_key, list_keys, lock_unrevoked_admins, revoke_key
from app.realtime.hub import Hub
from app.realtime.ws import CLOSE_SESSION_EXPIRED

router = APIRouter(prefix="/keys", tags=["keys"])


class KeyNotFound(AppError):
    status_code = 404
    code = "key_not_found"


class LastAdminKey(AppError):
    """At least one unrevoked admin key remains, or nobody could manage the app (SD30)."""

    status_code = 409
    code = "last_admin_key"


class CreateKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class CreatedKey(BaseModel):
    key_id: int
    key: str


class KeyInfo(BaseModel):
    key_id: int
    label: str
    role: Role
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


@router.get("")
async def get_keys(
    request: Request, _: Annotated[Principal, Depends(require_role("admin"))]
) -> list[KeyInfo]:
    async with db_engine(request).connect() as conn:
        keys = await list_keys(conn)
    return [
        KeyInfo(
            key_id=k.key_id,
            label=k.label,
            role=k.role,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            revoked=k.revoked,
        )
        for k in keys
    ]


@router.post("", status_code=201)
async def post_key(
    body: CreateKeyRequest,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> CreatedKey:
    async with db_engine(request).begin() as conn:
        key = await issue_key(conn, role=body.role, label=body.label)
    parsed = parse_key(key)
    assert parsed is not None
    return CreatedKey(key_id=parsed.key_id, key=key)


@router.delete("/{key_id}", status_code=204)
async def delete_key(
    key_id: int,
    request: Request,
    _: Annotated[Principal, Depends(require_role("admin"))],
    _draining: Annotated[None, Depends(refuse_while_draining)],
) -> Response:
    async with db_engine(request).begin() as conn:
        admins = await lock_unrevoked_admins(conn)
        key = await get_key(conn, key_id)
        if key is None:
            raise KeyNotFound(f"no key {key_id}")
        if admins == [key_id]:
            raise LastAdminKey(f"key {key_id} is the last unrevoked admin key")
        await revoke_key(conn, key_id)
    hub: Hub = request.app.state.hub
    hub.close_key(key_id, CLOSE_SESSION_EXPIRED)
    return Response(status_code=204)

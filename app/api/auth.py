"""Login, logout and "who am I" (Phase 3 SD1, SD2, SD6-SD8).

Login is rate-limited per client IP before the key is parsed or hashed (SD7),
then costs exactly one argon2 verify off the event loop for any well-formed key
(SD6). Success writes `last_used_at` -- the only request that writes to
`auth_key` -- and sets the session cookie: `HttpOnly`, `SameSite=Strict` and
`Secure` per `SESSION_COOKIE_SECURE` (SD8). The body is `{key}`, never echoed
back in an error.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import security
from app.api.deps import (
    ALL_ROLES,
    SESSION_COOKIE,
    Principal,
    Unauthenticated,
    clock_of,
    db_engine,
    require_role,
    settings_of,
)
from app.core.errors import AppError
from app.db.keys import AuthKeyRow, Role, get_key, touch_last_used

router = APIRouter(prefix="/auth", tags=["auth"])


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, Field(min_length=1, max_length=256)]


class Me(BaseModel):
    role: Role
    label: str
    allowed_routes: list[str]


def _me(role: Role, label: str) -> Me:
    return Me(role=role, label=label, allowed_routes=list(security.ROLE_ROUTES[role]))


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> Me:
    limiter: security.LoginLimiter = request.app.state.login_limiter
    client = request.client.host if request.client else "unknown"
    retry_after = limiter.check(client)
    if retry_after is not None:
        raise RateLimited(
            "too many login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    engine = db_engine(request)

    async def lookup(key_id: int) -> AuthKeyRow | None:
        async with engine.connect() as conn:
            return await get_key(conn, key_id)

    # Looked up on the module at call time, so a test can count the verifies.
    row = await security.verify_login(body.key, lookup, verifier=security.verify_secret)
    if row is None:
        raise Unauthenticated("that key is not valid")
    async with engine.begin() as conn:
        await touch_last_used(conn, row.key_id)

    settings = settings_of(request)
    token, _ = security.issue_session(
        row.key_id, row.role, secret=settings.jwt_secret, now_ms=clock_of(request).wall_ms()
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=security.SESSION_MS // 1000,
        path="/",
        **security.cookie_kwargs(settings),
    )
    return _me(row.role, row.label)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    _: Annotated[Principal, Depends(require_role(*ALL_ROLES))],
) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", **security.cookie_kwargs(settings_of(request)))


@router.get("/me")
async def me(principal: Annotated[Principal, Depends(require_role(*ALL_ROLES))]) -> Me:
    return _me(principal.role, principal.label)

"""Request dependencies: who is asking (SD8), and the process-wide objects on `app.state`.

`require_role(*roles)` is the one authorization dependency. It reads the
session cookie, checks the token with `read_session` on the injected clock,
then loads the `auth_key` row by primary key on every request, so a revoked key
is refused on its next request rather than at expiry (SD8, AC6e). The row is
authoritative (plan PD20): revoked, missing, or a role differing from the
token's is 401. A valid session whose role is not allowed is 403.

`tests/meta/test_route_authorization.py` finds this dependency in every
route's dependant tree by the `REQUIRE_ROLE_MARKER` attribute it carries
(SD4); a route without it must be on the public allowlist.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import read_session
from app.core.config import Settings
from app.core.errors import AppError
from app.db.keys import Role, get_key
from app.runtime.clock import Clock

SESSION_COOKIE: Final = "bb_session"
REQUIRE_ROLE_MARKER: Final = "__require_role__"
ALL_ROLES: Final[tuple[Role, ...]] = ("display", "bar", "admin")


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class ShuttingDown(AppError):
    status_code = 503
    code = "shutting_down"


@dataclass(frozen=True)
class Principal:
    key_id: int
    role: Role
    label: str
    exp_ms: int


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def clock_of(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def db_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


async def authenticate(
    *, token: str | None, settings: Settings, clock: Clock, engine: AsyncEngine
) -> Principal:
    """The session's principal, or `Unauthenticated`. Shared by HTTP routes and `/ws` (T26)."""
    if not token:
        raise Unauthenticated("no session")
    claims = read_session(token, secret=settings.jwt_secret, now_ms=clock.wall_ms())
    if claims is None:
        raise Unauthenticated("the session is invalid or has expired")
    async with engine.connect() as conn:
        row = await get_key(conn, claims.key_id)
    if row is None or row.revoked or row.role != claims.role:
        raise Unauthenticated("the session's key is no longer valid")
    return Principal(key_id=row.key_id, role=row.role, label=row.label, exp_ms=claims.exp_ms)


def require_role(*roles: Role) -> Callable[[Request], Awaitable[Principal]]:
    """A dependency admitting a valid session whose key has one of `roles`."""
    if not roles or any(role not in ALL_ROLES for role in roles):
        raise ValueError(f"require_role needs one or more of {ALL_ROLES}, got {roles}")
    allowed = frozenset(roles)

    async def dependency(request: Request) -> Principal:
        principal = await authenticate(
            token=request.cookies.get(SESSION_COOKIE),
            settings=settings_of(request),
            clock=clock_of(request),
            engine=db_engine(request),
        )
        if principal.role not in allowed:
            raise Forbidden(f"the {principal.role} role may not do this")
        return principal

    setattr(dependency, REQUIRE_ROLE_MARKER, allowed)
    return dependency


def refuse_while_draining(request: Request) -> None:
    """A write's dependency: 503 `shutting_down` once the process drains (Phase 6 SD24).

    Declare it as a parameter *after* the route's `require_role` one, so a role
    that may not write is still 401/403 while draining (PD19). A decorator's
    `dependencies=[...]` would run it first.
    """
    if getattr(request.app.state, "draining", False):
        raise ShuttingDown("the server is shutting down; try again in a moment")

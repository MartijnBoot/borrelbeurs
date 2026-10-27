"""Access keys, sessions, the login limiter and the Origin check (Phase 3 SD2, SD5-SD9; B-08).

A key is 9 symbols of Crockford base32, drawn from `secrets` and shown grouped
as `K7M-4QX-9PR` (B-08 SD1). It carries no `key_id`. It is read forgivingly:
case, spaces and dashes are ignored and `O`, `I`, `L` read as `0`, `1`, `1`
(SD2). Only its argon2id hash is stored, under a fixed salt and pinned
parameters (SD3), so the same key always hashes the same and login finds the
row by that hash: one hash per well-formed attempt, never a walk over the keys.
The key itself is shown once, by `app.cli.keys` or `POST /api/keys`, and never
written anywhere.

**Sessions (SD8).** HS256 JWTs carrying `sub` (the `key_id`), `role` and `exp`,
valid 24 hours. `exp` is checked against the injected time, not PyJWT's wall
clock, so expiry is testable on the fake clock. The `auth_key` row stays
authoritative: the dependency (T17) reloads it on every request.

**The login limiter (SD7)** counts attempts per client IP over a rolling 60 s
on the injected monotonic clock, before any parsing or hashing. A refused
attempt is not counted: it never reached the key, and counting it would let a
client hold itself out indefinitely by retrying.

**Origin (SD9).** An unsafe request, or the WebSocket handshake, must carry an
`Origin` whose host and port are exactly the request's own `Host`.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, cast
from urllib.parse import urlsplit

import jwt
from argon2.low_level import Type
from argon2.low_level import hash_secret as argon2_hash_secret
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import AppError
from app.db.keys import ROLES, AuthKeyRow, Role, insert_key
from app.runtime import crockford
from app.runtime.clock import Clock

# --- keys (B-08 SD1-SD3) ------------------------------------------------------------

KEY_LENGTH: Final = 9

# Drawn once with `secrets.token_hex(16)` and never changed: every stored key is
# found by its hash under this salt, so a new salt would make every key unfindable.
_KEY_SALT: Final = bytes.fromhex("c77cf770c7ef3c145727c41bcac25ec1")
# `PasswordHasher()`'s defaults when B-08 shipped (RFC 9106, low memory), pinned so
# a library upgrade cannot change the stored form (plan PD2).
_KEY_PARAMS: Final[dict[str, Any]] = {
    "time_cost": 3,
    "memory_cost": 65536,
    "parallelism": 4,
    "hash_len": 32,
    "type": Type.ID,
}


@dataclass(frozen=True)
class IssuedKey:
    key_id: int
    key: str


class KeyDrawExhausted(AppError):
    """Every draw collided with a stored hash; nothing was written (SD3).

    An `AppError` with its defaults, so `POST /api/keys` answers the generic 500
    `internal_error`; the CLI catches it and exits 1.
    """


def new_key_symbols() -> str:
    return crockford.draw(KEY_LENGTH)


def normalise_key(raw: str) -> str | None:
    """The key's 9 stored symbols, read forgivingly (SD2), or `None` if malformed."""
    return crockford.read(raw, KEY_LENGTH)


def display_key(symbols: str) -> str:
    return f"{symbols[:3]}-{symbols[3:6]}-{symbols[6:]}"


def key_hash(symbols: str) -> str:
    """The fixed-salt argon2id hash a key is stored and found by, `$argon2id$v=19$...`."""
    return argon2_hash_secret(symbols.encode(), _KEY_SALT, **_KEY_PARAMS).decode("ascii")


_MAX_DRAWS: Final = 5


async def issue_key(
    conn: AsyncConnection, *, role: Role, label: str, draw: Callable[[], str] | None = None
) -> IssuedKey:
    """Mint a key in the caller's transaction: its `key_id`, and the key, the only time it exists.

    Each draw is hashed and inserted in one statement. A hash any row already
    holds, revoked or not, inserts nothing, and the key is drawn again, up to 5
    times; then `KeyDrawExhausted`, with nothing inserted (SD3). `new_key_symbols`
    is looked up at call time, so a test can force a collision. Shared by
    `app.cli.keys create` and `POST /api/keys` (Phase 6 SD30).
    """
    for _ in range(_MAX_DRAWS):
        symbols = (draw or new_key_symbols)()
        key_id = await insert_key(conn, label=label, role=role, secret_hash=key_hash(symbols))
        if key_id is not None:
            return IssuedKey(key_id=key_id, key=display_key(symbols))
    raise KeyDrawExhausted(f"no free key after {_MAX_DRAWS} draws")


# --- roles (SD2) ----------------------------------------------------------------

ROLE_ROUTES: Final[dict[Role, tuple[str, ...]]] = {
    "display": ("/koers",),
    "bar": ("/bar", "/manipulation"),
    "admin": ("/", "/koers", "/bar", "/manipulation", "/settings", "/analytics", "/kassa"),
    "kassa": ("/kassa",),
}


# --- sessions (SD8) ---------------------------------------------------------------

SESSION_MS: Final = 24 * 60 * 60 * 1000
# A session's `sub`: the `key_id`, all digits.
_KEY_ID = re.compile(r"[1-9][0-9]{0,18}")
_ALGORITHM: Final = "HS256"


@dataclass(frozen=True)
class Claims:
    key_id: int
    role: Role
    exp_ms: int


def issue_session(key_id: int, role: Role, *, secret: str, now_ms: int) -> tuple[str, int]:
    """A signed session token and its expiry in epoch milliseconds."""
    exp_ms = now_ms + SESSION_MS
    claims = {"sub": str(key_id), "role": role, "exp": exp_ms // 1000}
    return jwt.encode(claims, secret, algorithm=_ALGORITHM), exp_ms


def read_session(token: str, *, secret: str, now_ms: int) -> Claims | None:
    """The token's claims if it is ours, well-formed and unexpired at `now_ms`; else `None`."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False, "require": ["sub", "role", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    sub, role, exp = claims["sub"], claims["role"], claims["exp"]
    if not (isinstance(sub, str) and _KEY_ID.fullmatch(sub)) or role not in ROLES:
        return None
    if not isinstance(exp, int) or now_ms >= exp * 1000:
        return None
    return Claims(key_id=int(sub), role=cast(Role, role), exp_ms=exp * 1000)


def cookie_kwargs(settings: Settings) -> dict[str, Any]:
    """The session cookie's attributes; `secure` is refused off in production (T3)."""
    return {"httponly": True, "samesite": "strict", "secure": settings.session_cookie_secure}


# --- the login limiter (SD7) ------------------------------------------------------

_WINDOW_S: Final = 60.0


class LoginLimiter:
    def __init__(self, rate_per_minute: int, clock: Clock) -> None:
        self._rate = rate_per_minute
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}

    @property
    def tracked_ips(self) -> int:
        return len(self._attempts)

    def check(self, ip: str) -> int | None:
        """Record an attempt from `ip`, or refuse it: `None`, or seconds until it may retry."""
        now = self._clock.monotonic()
        self._forget_idle(now)
        attempts = self._attempts.setdefault(ip, deque())
        if len(attempts) >= self._rate:
            return max(1, math.ceil(attempts[0] + _WINDOW_S - now))
        attempts.append(now)
        return None

    def _forget_idle(self, now: float) -> None:
        for ip in list(self._attempts):
            attempts = self._attempts[ip]
            while attempts and attempts[0] <= now - _WINDOW_S:
                attempts.popleft()
            if not attempts:
                del self._attempts[ip]


# --- Origin (SD9) ------------------------------------------------------------------


def same_origin(origin: str | None, host: str | None) -> bool:
    """Whether `origin` names exactly the request's own `host` (and port), over http(s)."""
    if not origin or not host:
        return False
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.path or parts.query or parts.username:
        return False
    return bool(parts.netloc) and parts.netloc.lower() == host.lower()


# --- login (B-08 SD3) ------------------------------------------------------------


async def find_login(
    raw_key: str,
    lookup: Callable[[str], Awaitable[AuthKeyRow | None]],
    *,
    hasher: Callable[[str], str] = key_hash,
) -> AuthKeyRow | None:
    """The key's active row, or `None` (B-08 SD3).

    A malformed key costs nothing. Any well-formed key -- unknown, revoked or
    valid -- costs exactly one argon2 hash, in a worker thread, and one lookup by
    that hash, so timing does not reveal whether a key exists.
    """
    symbols = normalise_key(raw_key)
    if symbols is None:
        return None
    row = await lookup(await asyncio.to_thread(hasher, symbols))
    if row is None or row.revoked:
        return None
    return row


# --- the Origin middleware (SD9) ----------------------------------------------------

UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginGuard:
    """Pure-ASGI middleware: an unsafe HTTP request without a same-origin `Origin` is 403.

    Browsers send cookies on cross-site form posts; with no CORS middleware at all
    (one origin, AC6b) this check is the CSRF defence. The WebSocket handshake gets
    the same check in the `/ws` handler, before accept (SD31).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            headers = Headers(scope=scope)
            if not same_origin(headers.get("origin"), headers.get("host")):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "origin_mismatch",
                            "message": "this request must come from this site",
                        }
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

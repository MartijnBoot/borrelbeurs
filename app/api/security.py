"""Access keys, sessions, the login limiter and the Origin check (Phase 3 SD2, SD5-SD9; PD2, PD18).

A key is `bb_<key_id>_<secret>`, with `secret = secrets.token_urlsafe(32)`
(43 characters of `[A-Za-z0-9_-]`). It is parsed by `split("_", 2)` with an
all-digit `key_id`, so an `_` inside the secret is safe. Only the argon2id hash
of the secret is stored (`argon2.PasswordHasher` defaults, RFC 9106); the key
itself is printed once by `app.cli.keys` and never written anywhere.

`dummy_hash()` is what login verifies against when no stored hash exists, so
an unknown `key_id` costs the same argon2 verify as a real one (SD6). It is
built on first use, never at import: hashing at import would slow every
process start, test collection included.

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
import secrets
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from typing import Any, Final, cast
from urllib.parse import urlsplit

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.db.keys import ROLES, AuthKeyRow, Role
from app.runtime.clock import Clock

KEY_PREFIX: Final = "bb"

# token_urlsafe(32) is 43 characters; the bound only stops an absurd input from
# reaching argon2.
_SECRET = re.compile(r"[A-Za-z0-9_-]{1,128}")
_KEY_ID = re.compile(r"[1-9][0-9]{0,18}")

_hasher = PasswordHasher()


@dataclass(frozen=True)
class ParsedKey:
    key_id: int
    secret: str


def mint_secret() -> str:
    return secrets.token_urlsafe(32)


def format_key(key_id: int, secret: str) -> str:
    return f"{KEY_PREFIX}_{key_id}_{secret}"


def parse_key(raw: str) -> ParsedKey | None:
    """`raw` split into `key_id` and secret, or `None` if malformed. Never hashes."""
    parts = raw.split("_", 2)
    if len(parts) != 3:
        return None
    prefix, key_id, secret = parts
    if prefix != KEY_PREFIX or not _KEY_ID.fullmatch(key_id) or not _SECRET.fullmatch(secret):
        return None
    return ParsedKey(key_id=int(key_id), secret=secret)


def hash_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_secret(secret_hash: str, secret: str) -> bool:
    """Whether `secret` matches `secret_hash`; any malformed hash is simply no match."""
    try:
        return _hasher.verify(secret_hash, secret)
    except (VerificationError, InvalidHashError):
        return False


@cache
def dummy_hash() -> str:
    """A hash no presented secret matches, built once, on first use."""
    return hash_secret(mint_secret())


# --- roles (SD2) ----------------------------------------------------------------

ROLE_ROUTES: Final[dict[Role, tuple[str, ...]]] = {
    "display": ("/koers",),
    "bar": ("/bar", "/manipulation"),
    "admin": ("/", "/koers", "/bar", "/manipulation", "/settings"),
}


# --- sessions (SD8) ---------------------------------------------------------------

SESSION_MS: Final = 24 * 60 * 60 * 1000
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


# --- login (SD6) -------------------------------------------------------------------


async def verify_login(
    raw_key: str,
    lookup: Callable[[int], Awaitable[AuthKeyRow | None]],
    *,
    verifier: Callable[[str, str], bool] = verify_secret,
) -> AuthKeyRow | None:
    """The key's active row, or `None`.

    A malformed key costs nothing. Any well-formed key -- unknown, revoked, wrong
    or right -- costs exactly one argon2 verify, in a worker thread, against the
    stored hash or the dummy, so timing does not reveal whether a `key_id` exists.
    """
    parsed = parse_key(raw_key)
    if parsed is None:
        return None
    row = await lookup(parsed.key_id)
    # The first dummy_hash() is a full argon2 hash: build it off the loop too.
    stored = row.secret_hash if row is not None else await asyncio.to_thread(dummy_hash)
    matched = await asyncio.to_thread(verifier, stored, parsed.secret)
    if row is None or not matched or row.revoked:
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

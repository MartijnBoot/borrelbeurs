"""Security primitives (Phase 3 T15: SD2, SD6, SD7, SD8, SD9 pure parts; AC5, AC6, AC6a, AC6b)."""

from __future__ import annotations

import base64
import json

import jwt
import pytest

from app.api.security import (
    ROLE_ROUTES,
    SESSION_MS,
    Claims,
    LoginLimiter,
    cookie_kwargs,
    issue_session,
    read_session,
    same_origin,
)
from app.core.config import Settings
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
SECRET = "0123456789abcdef0123456789abcdef"


def test_the_role_route_table_is_sd2s() -> None:
    assert ROLE_ROUTES == {
        "display": ("/koers",),
        "bar": ("/bar", "/manipulation"),
        "admin": ("/", "/koers", "/bar", "/manipulation", "/settings", "/analytics", "/kassa"),
        "kassa": ("/kassa",),
    }


# --- sessions (SD8) ---------------------------------------------------------------


def test_a_session_lasts_24_hours_and_reads_back() -> None:
    token, exp_ms = issue_session(42, "bar", secret=SECRET, now_ms=T0)

    assert SESSION_MS == 24 * 3_600_000
    assert exp_ms == T0 + SESSION_MS
    assert read_session(token, secret=SECRET, now_ms=T0) == Claims(
        key_id=42, role="bar", exp_ms=exp_ms
    )
    assert read_session(token, secret=SECRET, now_ms=exp_ms - 1) is not None


def test_an_expired_session_is_none_on_the_injected_clock() -> None:
    """`exp` is checked against `now_ms`, not PyJWT's wall clock."""
    token, exp_ms = issue_session(42, "bar", secret=SECRET, now_ms=T0)

    assert read_session(token, secret=SECRET, now_ms=exp_ms) is None
    # Far in the past by the real clock, still valid on the injected one:
    old, _ = issue_session(42, "bar", secret=SECRET, now_ms=1_000_000_000_000)
    assert read_session(old, secret=SECRET, now_ms=1_000_000_000_000) is not None


def _tamper(token: str, **claims: object) -> str:
    header, payload, signature = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data.update(claims)
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{header}.{forged}.{signature}"


def test_a_tampered_or_foreign_token_is_none() -> None:
    token, _ = issue_session(42, "bar", secret=SECRET, now_ms=T0)

    assert read_session(_tamper(token, role="admin"), secret=SECRET, now_ms=T0) is None
    assert read_session(token, secret=SECRET[::-1], now_ms=T0) is None
    assert read_session("not.a.token", secret=SECRET, now_ms=T0) is None
    assert read_session("", secret=SECRET, now_ms=T0) is None


def test_an_unsigned_or_wrong_algorithm_token_is_none() -> None:
    claims = {"sub": "42", "role": "admin", "exp": (T0 + SESSION_MS) // 1000}

    unsigned = jwt.encode(claims, key=None, algorithm="none")
    hs512 = jwt.encode(claims, SECRET + "x" * 32, algorithm="HS512")

    assert read_session(unsigned, secret=SECRET, now_ms=T0) is None
    assert read_session(hs512, secret=SECRET, now_ms=T0) is None


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "42", "role": "root"},
        {"sub": "abc", "role": "bar"},
        {"role": "bar"},
        {"sub": "42"},
        {"sub": 42, "role": "bar"},
    ],
)
def test_a_well_signed_token_with_bad_claims_is_none(claims: dict[str, object]) -> None:
    token = jwt.encode({**claims, "exp": (T0 + SESSION_MS) // 1000}, SECRET, algorithm="HS256")

    assert read_session(token, secret=SECRET, now_ms=T0) is None


# --- the login limiter (SD7, AC5) ------------------------------------------------


def test_the_eleventh_attempt_in_sixty_seconds_is_limited_and_the_window_rolls() -> None:
    clock = FakeClock(T0)
    limiter = LoginLimiter(10, clock)

    allowed = []
    for _ in range(10):
        allowed.append(limiter.check("10.0.0.1"))
        clock.advance(5_000)  # attempts at 0, 5, ..., 45 s
    assert allowed == [None] * 10

    assert limiter.check("10.0.0.1") == 10  # at 50 s; the 0 s attempt leaves at 60 s
    assert limiter.check("10.0.0.2") is None  # per IP
    clock.advance(9_000)
    assert limiter.check("10.0.0.1") == 1  # at 59 s
    clock.advance(1_000)
    assert limiter.check("10.0.0.1") is None  # at 60 s the first attempt has rolled out
    assert limiter.check("10.0.0.1") == 5  # at 60 s again: the 5 s attempt leaves at 65 s


def test_a_limited_attempt_does_not_extend_the_window() -> None:
    """A 429 never reaches parsing or hashing, so it is not an attempt that counts."""
    clock = FakeClock(T0)
    limiter = LoginLimiter(2, clock)
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    for _ in range(30):
        clock.advance(1_000)
        limiter.check("ip")
    clock.advance(30_000)

    assert limiter.check("ip") is None


def test_the_limiter_forgets_idle_ips() -> None:
    clock = FakeClock(T0)
    limiter = LoginLimiter(10, clock)
    for n in range(100):
        limiter.check(f"10.0.0.{n}")
    clock.advance(61_000)
    limiter.check("10.0.1.1")

    assert limiter.tracked_ips == 1


# --- Origin (SD9) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "host", "same"),
    [
        ("https://bar.example", "bar.example", True),
        ("http://192.168.1.10:8000", "192.168.1.10:8000", True),
        ("https://BAR.example", "bar.example", True),
        ("https://bar.example:8443", "bar.example", False),
        ("https://bar.example", "bar.example:8443", False),
        ("https://evil.example", "bar.example", False),
        ("https://bar.example.evil", "bar.example", False),
        ("bar.example", "bar.example", False),
        ("null", "bar.example", False),
        ("", "bar.example", False),
        (None, "bar.example", False),
        ("https://bar.example", None, False),
        ("ftp://bar.example", "bar.example", False),
        ("https://user@bar.example", "bar.example", False),
        ("https://bar.example/path", "bar.example", False),
    ],
)
def test_same_origin(origin: str | None, host: str | None, same: bool) -> None:
    assert same_origin(origin, host) is same


# --- the cookie (SD8, AC6a) --------------------------------------------------------


@pytest.mark.parametrize("secure", [True, False])
def test_cookie_attributes(secure: bool) -> None:
    settings = Settings.model_construct(session_cookie_secure=secure)

    assert cookie_kwargs(settings) == {"httponly": True, "samesite": "strict", "secure": secure}

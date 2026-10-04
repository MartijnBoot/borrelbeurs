"""AC2 — a missing or malformed environment variable fails the boot, by name.

The point of every assertion below is not that *an* exception was raised, but
that the message tells the operator **which** variable to fix. A boot failure
that says only "validation error" costs an evening at a borrel.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import ConfigError, get_settings

ENV_VARS = (
    "DATABASE_URL",
    "JWT_SECRET",
    "PORT",
    "LOG_LEVEL",
    "APP_ENV",
    "LOGIN_RATE_PER_MINUTE",
    "SESSION_COOKIE_SECURE",
)

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# A complete, valid environment. Test values only -- no real credentials.
COMPLETE_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
    "JWT_SECRET": "0123456789abcdef0123456789abcdef",  # exactly 32 characters
    "PORT": "8123",
    "LOG_LEVEL": "WARNING",
    "APP_ENV": "ci",
}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty environment and an empty settings cache.

    Without this, a developer's own exported `DATABASE_URL` would make the
    "missing variable" tests pass for the wrong reason, and `get_settings()`'s
    cache would leak one test's environment into the next.
    """
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read a `KEY=value` file, ignoring blank lines and `#` comments."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        values[name.strip()] = value.strip()
    return values


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    """Apply the complete environment, then the overrides. `None` means omit."""
    env = {**COMPLETE_ENV, **overrides}
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_missing_database_url_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, DATABASE_URL=None)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "DATABASE_URL" in str(excinfo.value)


def test_short_jwt_secret_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_secret = "0123456789"  # 10 characters, below the 32-character floor
    _set_env(monkeypatch, JWT_SECRET=short_secret)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "JWT_SECRET" in message
    # The message is going to land in a log. It names the variable; it must
    # never quote the rejected secret back.
    assert short_secret not in message


def test_non_numeric_port_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, PORT="banana")

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "PORT" in str(excinfo.value)


# --- DATABASE_URL shape (R13) ------------------------------------------------
#
# T3 left `database_url` at `min_length=1` so as not to pre-judge the driver.
# T7 is the task that creates the engine, so the shape lands here. AC2 says
# "missing **or malformed**": a sync `postgresql://` DSN or a typo'd scheme must
# fail at boot naming the variable, not surface three layers down as an asyncpg
# dialect error at the first query.

MALFORMED_DATABASE_URLS = [
    pytest.param("x", id="not-a-url-at-all"),
    pytest.param("   ", id="whitespace-only"),
    pytest.param(
        "postgresql://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
        id="sync-driver-no-plus-asyncpg",
    ),
    pytest.param(
        "postgres://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
        id="heroku-style-postgres-scheme",
    ),
    pytest.param(
        "postgresql+psycopg://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
        id="wrong-driver",
    ),
    pytest.param(
        "postgresql+asyncpq://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
        id="typo-in-the-driver",
    ),
    pytest.param("postgresql+asyncpg://", id="no-host-no-database"),
    pytest.param("postgresql+asyncpg://localhost:5432", id="host-but-no-database"),
    pytest.param("postgresql+asyncpg://localhost:5432/", id="empty-database-name"),
    pytest.param("postgresql+asyncpg:///borrelbeurs", id="database-but-no-host"),
    # The two cases `urlsplit` only objects to when the port is *read*. They
    # passed validation until the reader moved inside the try block: urlsplit
    # itself is lazy, and `SplitResult.port` is where the ValueError comes
    # from. asyncpg would have failed on both, far from the typo.
    pytest.param(
        "postgresql+asyncpg://borrelbeurs:borrelbeurs@localhost:banana/borrelbeurs",
        id="non-numeric-port",
    ),
    pytest.param(
        "postgresql+asyncpg://borrelbeurs:borrelbeurs@localhost:99999/borrelbeurs",
        id="port-out-of-range",
    ),
]


@pytest.mark.parametrize("value", MALFORMED_DATABASE_URLS)
def test_malformed_database_url_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_env(monkeypatch, DATABASE_URL=value)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "DATABASE_URL" in str(excinfo.value)


def test_malformed_database_url_does_not_leak_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DSN carries the database password; a rejection message must not.

    The sync-driver case is the realistic one -- someone pastes a hosting
    provider's `postgresql://` URL, complete with a real password, and the boot
    failure goes straight into a log.
    """
    _set_env(monkeypatch, DATABASE_URL="postgresql://someone:hunter2@db.example.com:5432/prod")

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert "hunter2" not in message
    # The scheme is the thing the operator has to change, and carries no
    # secret, so naming it is the whole point of the message.
    assert "postgresql+asyncpg" in message


def test_a_malformed_port_is_rejected_without_echoing_the_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T3's no-echo property, on the branch that was previously unreachable.

    The malformed-port rejection is the one message assembled in a different
    place from the others, so it gets its own proof that nothing from the DSN
    -- password, host, database, or the bad port itself -- reaches either the
    message or a rendered traceback. `format_exception` is checked as well as
    `str()` because `from None` is what keeps pydantic's chained error, which
    quotes the rejected input, out of the log.
    """
    dsn = "postgresql+asyncpg://someone:hunter2@db.example.com:banana/prodsecret"
    _set_env(monkeypatch, DATABASE_URL=dsn)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    rendered = "".join(traceback.format_exception(excinfo.value))

    assert "DATABASE_URL" in message
    for fragment in ("hunter2", "someone", "db.example.com", "prodsecret", "banana", dsn):
        assert fragment not in message, f"the rejection message echoes {fragment!r}"
        assert fragment not in rendered, f"the traceback echoes {fragment!r}"


WORKABLE_DATABASE_URLS = [
    pytest.param(
        "postgresql+asyncpg://borrelbeurs:borrelbeurs@localhost:5432/borrelbeurs",
        id="docker-compose-local",
    ),
    pytest.param(
        "postgresql+asyncpg://test:test@localhost:49173/test",
        id="testcontainers-ephemeral-port",
    ),
    pytest.param(
        "postgresql+asyncpg://borrelbeurs:borrelbeurs@db:5432/borrelbeurs",
        id="compose-network-hostname",
    ),
    pytest.param(
        "postgresql+asyncpg://user:p%40ss%2Fword@host.example.com:5432/db?ssl=require",
        id="encoded-password-and-query-string",
    ),
]


@pytest.mark.parametrize("value", WORKABLE_DATABASE_URLS)
def test_database_url_admits_the_shapes_we_actually_hand_it(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The constraint has to be tight *and* workable.

    Alembic gets the compose URL; Phase 2's integration tests get whatever
    `PostgresContainer.get_connection_url(driver="asyncpg")` hands back, which
    is the same shape on an ephemeral port. Tightening the scheme must not
    exclude either.
    """
    _set_env(monkeypatch, DATABASE_URL=value)

    assert get_settings().database_url == value


def test_the_committed_database_url_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R19 -- the DSN a developer copies out of `.env.example` must validate.

    `.env.example` is the contract between this module and `docker-compose.yml`:
    AC1 promises that copying it, starting Postgres and applying migrations
    needs no further manual steps. If the shipped DATABASE_URL failed its own
    schema, the first `alembic upgrade` would break and it would look like a bug
    in `scripts/setup.sh`. Read from the real file, never retyped.
    """
    committed = _parse_env_file(ENV_EXAMPLE)["DATABASE_URL"]
    _set_env(monkeypatch, DATABASE_URL=committed)

    assert get_settings().database_url == committed


def test_committed_env_example_cannot_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped template must refuse to start, and say that JWT_SECRET is why.

    `.env.example` is public. If its JWT_SECRET placeholder were long enough to
    pass validation, copying the file unedited -- by hand, or by pasting it into
    a hosting provider's environment group -- would produce a *running* app whose
    session-signing key is in the repository, and therefore forgeable admin
    sessions. The placeholder is short on purpose; this test is what keeps it so.

    The values are parsed out of the real artifact rather than hard-coded, so an
    edit to `.env.example` is what this test tracks.
    """
    example = _parse_env_file(ENV_EXAMPLE)
    assert "JWT_SECRET" in example, f"{ENV_EXAMPLE} no longer defines JWT_SECRET"
    for name, value in example.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "JWT_SECRET" in str(excinfo.value)


def test_settings_do_not_print_their_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R17 — rendering a `Settings` must not spill `JWT_SECRET` or the DSN password.

    `ConfigError` is careful, but the model itself was not: `repr(settings)`
    printed both values in full, so one `logger.debug("settings=%s", settings)`
    would put a forgeable signing key in the log aggregator. Structured logging
    lands in T5, which is where this is settled.
    """
    _set_env(monkeypatch)
    settings = get_settings()

    for rendered in (repr(settings), str(settings), f"{settings}"):
        assert COMPLETE_ENV["JWT_SECRET"] not in rendered
        assert COMPLETE_ENV["DATABASE_URL"] not in rendered
        # ...while the harmless fields stay visible, or the repr is useless.
        assert "8123" in rendered


def test_complete_environment_constructs_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)

    settings = get_settings()

    assert settings.database_url == COMPLETE_ENV["DATABASE_URL"]
    assert settings.jwt_secret == COMPLETE_ENV["JWT_SECRET"]
    assert settings.port == 8123
    assert settings.log_level == "WARNING"
    assert settings.app_env == "ci"

    # PORT is the one optional variable with a value that matters: Render
    # injects it, and everywhere else it falls back to 8000 (plan D11).
    monkeypatch.delenv("PORT")
    get_settings.cache_clear()
    assert get_settings().port == 8000


def test_missing_jwt_secret_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3 AC4: no JWT_SECRET, no boot -- and the message says which variable."""
    _set_env(monkeypatch, JWT_SECRET=None)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "JWT_SECRET" in str(excinfo.value)


# --- Phase 3: login rate and session cookie (SD7, SD8) ---------------------------


def test_login_rate_and_cookie_security_default_to_ten_and_secure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)

    settings = get_settings()

    assert settings.login_rate_per_minute == 10
    assert settings.session_cookie_secure is True


def test_both_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, LOGIN_RATE_PER_MINUTE="25", SESSION_COOKIE_SECURE="false")

    settings = get_settings()

    assert settings.login_rate_per_minute == 25
    assert settings.session_cookie_secure is False


@pytest.mark.parametrize("value", ["0", "-1", "banana"])
def test_a_bad_login_rate_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_env(monkeypatch, LOGIN_RATE_PER_MINUTE=value)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "LOGIN_RATE_PER_MINUTE" in str(excinfo.value)


# --- the database timeout (Phase 3 follow-up: no unbounded wait on a silent database) ---


def test_the_database_timeout_defaults_to_five_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)

    assert get_settings().database_timeout_seconds == 5.0


def test_the_database_timeout_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, DATABASE_TIMEOUT_SECONDS="0.5")

    assert get_settings().database_timeout_seconds == 0.5


@pytest.mark.parametrize("value", ["0", "-1", "banana"])
def test_a_bad_database_timeout_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_env(monkeypatch, DATABASE_TIMEOUT_SECONDS=value)

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    assert "DATABASE_TIMEOUT_SECONDS" in str(excinfo.value)


def test_production_refuses_an_insecure_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6a (boot half), SD8: `Secure` may be switched off locally, never in production."""
    _set_env(monkeypatch, APP_ENV="production", SESSION_COOKIE_SECURE="false")

    with pytest.raises(ConfigError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "SESSION_COOKIE_SECURE" in message
    assert "production" in message


@pytest.mark.parametrize(
    ("app_env", "secure"), [("production", "true"), ("local", "false"), ("ci", "false")]
)
def test_an_insecure_cookie_is_allowed_outside_production(
    monkeypatch: pytest.MonkeyPatch, app_env: str, secure: str
) -> None:
    _set_env(monkeypatch, APP_ENV=app_env, SESSION_COOKIE_SECURE=secure)

    assert get_settings().session_cookie_secure is (secure == "true")

"""Application configuration — the one place this repository reads the environment.

Two rules hold here, and both are load-bearing.

**Nothing happens at import.** Importing this module reads no variable, opens
no file and creates no directory; the environment is touched only when
`get_settings()` is called. v1's `legacy/v1/backend/config.py:11-13` `mkdir`s
three directories at import time, which means merely importing it mutates the
filesystem — in a test, in a build, in a container being inspected. This module
must never acquire that habit.

**Boot fails loudly, by name.** `get_settings()` raises `ConfigError` listing
every variable that is missing or malformed, first offender first, so the
operator is told what to fix instead of meeting a stack trace at the first
query (spec AC2).

Nothing outside this module may read `os.environ`, `os.getenv` or a `.env`
file (spec AC3). Everything else takes a `Settings` instance.

Values come from the process environment only — this module loads no `.env`
file. `scripts/setup.sh` writes `.env.local`; exporting it is the caller's job
(`set -a; . ./.env.local; set +a`), which keeps "what the app is running with"
a property of the process rather than of the working directory.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AppEnv = Literal["local", "ci", "production"]

# The one DSN scheme this application can actually open a connection with.
# ADR 0004 fixes the engine (Postgres, local and hosted); the async driver
# follows from SQLAlchemy's async engine and Alembic's async `env.py`. A sync
# `postgresql://` URL is the common near-miss -- every hosting provider hands
# one out -- and it fails far from the mistake, so it is rejected at boot.
DATABASE_URL_SCHEME = "postgresql+asyncpg"

# Repeated in three rejection messages; a worked example beats a grammar.
DATABASE_URL_SHAPE = f"expected {DATABASE_URL_SCHEME}://user:password@host:port/database"


class ConfigError(RuntimeError):
    """The environment does not satisfy `Settings`. Raised at boot, never caught."""


class Settings(BaseSettings):
    """The complete set of environment variables this application understands.

    Field names map to their upper-case environment variable: `database_url`
    reads `DATABASE_URL`.

    The two secret-bearing fields are declared `repr=False`, so neither
    `repr(settings)` nor `str(settings)` -- and therefore no `%s` in a log call
    -- can print them (R17). `model_dump()` still returns the real values:
    serialising the settings on purpose is a different act from logging them by
    accident, and only the accident is worth designing against here.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # Required. Async SQLAlchemy URL for Postgres (ADR 0004). `repr=False`
    # because the DSN carries the database password (R17). The shape is
    # enforced by `_check_database_url_shape` below; `min_length` only makes
    # an empty value read as "missing" rather than "malformed".
    database_url: str = Field(min_length=1, repr=False)

    # Required. Signing key for session JWTs. 32 characters is the floor below
    # which a HS256 key is weaker than the hash it feeds. `repr=False` keeps it
    # out of `repr()`, `str()` and therefore out of `logger.info("%s", settings)`
    # (R17) -- the leak that costs most, since a leaked JWT_SECRET forges
    # admin sessions.
    jwt_secret: str = Field(min_length=32, repr=False)

    # Optional. Render injects $PORT; everywhere else this is 8000 (plan D11).
    port: int = Field(default=8000, ge=1, le=65535)

    log_level: LogLevel = "INFO"
    app_env: AppEnv = "local"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        """Accept `debug` as readily as `DEBUG`; the case carries no meaning."""
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def _check_database_url_shape(cls, value: str) -> str:
        """Reject a DSN this application could never connect with (AC2, R13).

        Checked: the scheme, a host, and a database name. Not checked: whether
        the credentials are right or the server is up -- that is a runtime fact
        and belongs to `/readyz`, not to boot validation.

        Every message below is assembled from parts of the URL that carry no
        secret. The scheme is named because it is the thing the operator has to
        change; the userinfo, host and path are never echoed back, because this
        message is expected to reach a log (R17).
        """
        try:
            parts = urlsplit(value)
            host = parts.hostname
            # `.port` is read here, inside the `try`, on purpose: urlsplit is
            # lazy and parses the port only when the attribute is accessed, so
            # `...@host:banana/db` and `...@host:99999/db` raise *here* or not
            # at all. Reading it elsewhere -- or not at all -- makes this
            # except branch dead code, which is what it was. (`.port` also
            # rejects a number outside 0-65535 for us.)
            _port = parts.port
        except ValueError:
            raise ValueError(f"is not a parseable URL; {DATABASE_URL_SHAPE}") from None

        if parts.scheme != DATABASE_URL_SCHEME:
            raise ValueError(
                f"must use the {DATABASE_URL_SCHEME}:// scheme "
                f"(this application drives Postgres asynchronously); "
                f"got scheme {parts.scheme!r}"
            )
        if not host:
            raise ValueError(f"names no host; {DATABASE_URL_SHAPE}")
        if parts.path in ("", "/"):
            raise ValueError(f"names no database; {DATABASE_URL_SHAPE}")
        return value


def _environment_variable(location: tuple[int | str, ...]) -> str:
    """Render a pydantic error location as the environment variable it came from."""
    return str(location[0]).upper() if location else "<unknown variable>"


def _describe(error: ValidationError) -> str:
    """Build the boot-failure message.

    Deliberately assembled from `loc` and `msg` only. `str(ValidationError)`
    quotes the rejected input back, which for `JWT_SECRET` would print the
    secret into the boot log.
    """
    faults = [
        f"  - {_environment_variable(detail['loc'])}: {detail['msg']}" for detail in error.errors()
    ]
    count = len(faults)
    plural = "" if count == 1 else "s"
    return "\n".join(
        [
            f"Invalid configuration: {count} environment variable{plural} missing or malformed.",
            *faults,
            "See .env.example for the expected values. The application will not start.",
        ]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read and validate the environment once per process.

    Raises:
        ConfigError: if any variable is missing or malformed. The message names
            each offending variable, in declaration order.
    """
    try:
        # pydantic's @dataclass_transform makes mypy synthesise an __init__
        # demanding every required field as a keyword argument. For a
        # BaseSettings that is precisely wrong: the values come from the
        # environment, and passing none of them is the intended call.
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        # `from None`: the chained ValidationError's repr contains the rejected
        # input values, and this exception is expected to reach a log.
        raise ConfigError(_describe(error)) from None

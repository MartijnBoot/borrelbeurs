"""AC2 — a missing or malformed environment variable fails the boot, by name.

The point of every assertion below is not that *an* exception was raised, but
that the message tells the operator **which** variable to fix. A boot failure
that says only "validation error" costs an evening at a borrel.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import ConfigError, get_settings

ENV_VARS = ("DATABASE_URL", "JWT_SECRET", "PORT", "LOG_LEVEL", "APP_ENV")

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

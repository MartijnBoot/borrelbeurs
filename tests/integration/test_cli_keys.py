"""`python -m app.cli.keys` (Phase 3 T10: SD5; AC6c storage half; AC6e CLI half)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.api.security import parse_key, verify_secret
from app.cli.keys import main
from app.core.config import Settings, get_settings
from app.db.session import create_engine

KEY_SHAPE = re.compile(r"bb_(\d+)_([A-Za-z0-9_-]{43})")


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """`main`'s environment, pointed at the per-test scratch database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _rows(settings: Settings, url: str) -> list[dict[str, Any]]:
    async def scenario() -> list[dict[str, Any]]:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT * FROM auth_key ORDER BY key_id"))
                return [dict(row._mapping) for row in result]
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _create(capsys: pytest.CaptureFixture[str], role: str = "bar", label: str = "Bar 1") -> str:
    assert main(["create", "--role", role, "--label", label]) == 0
    return capsys.readouterr().out.strip()


def test_create_prints_the_key_once_and_stores_only_its_argon2id_hash(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    key = _create(capsys, "admin", "Bestuur")
    match = KEY_SHAPE.fullmatch(key)
    assert match is not None, key
    parsed = parse_key(key)
    assert parsed is not None

    (row,) = _rows(settings, scratch)

    assert (row["key_id"], row["role"], row["label"]) == (parsed.key_id, "admin", "Bestuur")
    assert str(row["secret_hash"]).startswith("$argon2id$")
    assert verify_secret(row["secret_hash"], parsed.secret)
    for column, value in row.items():
        assert value != parsed.secret, f"auth_key.{column} holds the secret"
        assert value != key, f"auth_key.{column} holds the key"
        assert parsed.secret not in str(value), f"auth_key.{column} contains the secret"
    assert row["revoked_at"] is None
    assert row["last_used_at"] is None


def test_list_shows_id_label_role_status_and_nothing_secret(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    bar = _create(capsys, "bar", "Bar 1")
    display = _create(capsys, "display", "Beamer")
    stored = [str(row["secret_hash"]) for row in _rows(settings, scratch)]

    assert main(["list"]) == 0
    out = capsys.readouterr().out

    for key in (bar, display):
        parsed = parse_key(key)
        assert parsed is not None
        assert parsed.secret not in out
    for secret_hash in stored:
        assert secret_hash not in out
    assert "$argon2" not in out
    lines = out.splitlines()
    assert lines[0].split() == ["id", "label", "role", "status"]
    assert [line.split()[-2:] for line in lines[1:]] == [["bar", "active"], ["display", "active"]]


def test_revoke_sets_revoked_at_and_list_shows_it(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    key = _create(capsys)
    parsed = parse_key(key)
    assert parsed is not None

    assert main(["revoke", str(parsed.key_id)]) == 0
    capsys.readouterr()

    (row,) = _rows(settings, scratch)
    assert row["revoked_at"] is not None
    assert main(["list"]) == 0
    assert capsys.readouterr().out.splitlines()[1].split()[-1] == "revoked"


def test_revoking_an_unknown_key_exits_1(scratch: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["revoke", "999999"]) == 1

    assert "no key 999999" in capsys.readouterr().err


@pytest.mark.parametrize("label", ["", "   ", "x" * 101], ids=["empty", "blank", "101-chars"])
def test_a_bad_label_is_refused_and_nothing_is_written(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    assert main(["create", "--role", "bar", "--label", label]) == 2

    assert "--label" in capsys.readouterr().err
    assert _rows(settings, scratch) == []


def test_an_unknown_role_is_refused(scratch: str, settings: Settings) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["create", "--role", "root", "--label", "x"])

    assert excinfo.value.code == 2
    assert _rows(settings, scratch) == []

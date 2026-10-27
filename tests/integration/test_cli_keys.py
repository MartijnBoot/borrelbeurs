"""`python -m app.cli.keys` (Phase 3 T10: SD5; AC6c, AC6e CLI halves; B-08 AC1, AC3, AC8, AC9)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.api import security
from app.cli.keys import main
from app.core.config import Settings, get_settings
from app.db.session import create_engine

KEY_SHAPE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{3}(-[0-9A-HJKMNP-TV-Z]{3}){2}$")


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
    assert KEY_SHAPE.fullmatch(key), key
    assert "bb_" not in key
    symbols = security.normalise_key(key)
    assert symbols is not None

    (row,) = _rows(settings, scratch)

    assert (row["role"], row["label"]) == ("admin", "Bestuur")
    assert str(row["key_id"]) not in key.split("-")
    assert row["secret_hash"] == security.key_hash(symbols)
    for column, value in row.items():
        assert key not in str(value), f"auth_key.{column} holds the key"
        assert symbols not in str(value), f"auth_key.{column} holds the key's symbols"
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
        assert key not in out
        assert key.replace("-", "") not in out
    for secret_hash in stored:
        assert secret_hash not in out
    assert "$argon2" not in out
    lines = out.splitlines()
    assert lines[0].split() == ["id", "label", "role", "status"]
    assert [line.split()[-2:] for line in lines[1:]] == [["bar", "active"], ["display", "active"]]


def test_revoke_sets_revoked_at_and_list_shows_it(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    _create(capsys)
    (row,) = _rows(settings, scratch)

    assert main(["revoke", str(row["key_id"])]) == 0
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


def test_create_mints_a_kassa_key(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """B-05 SD7, AC40: `create --role kassa`."""
    key = _create(capsys, "kassa", "Kassa 1")
    symbols = security.normalise_key(key)
    assert symbols is not None

    (row,) = _rows(settings, scratch)

    assert (row["role"], row["label"]) == ("kassa", "Kassa 1")
    assert row["secret_hash"] == security.key_hash(symbols)


def test_create_gives_up_after_five_collisions_and_writes_nothing(
    scratch: str,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-08 AC9, CLI half: exit 1, the message, and no new row."""
    taken = security.normalise_key(_create(capsys))
    assert taken is not None
    monkeypatch.setattr(security, "new_key_symbols", lambda: taken)

    assert main(["create", "--role", "bar", "--label", "Bar 2"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "keys: no free key after 5 draws, nothing written"
    assert len(_rows(settings, scratch)) == 1

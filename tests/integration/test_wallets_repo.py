"""The wallet repository (B-05 T4: SD3, SD9, SD14, SD15; AC4, AC5, AC12, AC29, AC32, AC47)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import (
    NameTaken,
    WalletNotFound,
    WalletRow,
    WalletSettingsRow,
)
from app.runtime import wallet_codes

T = TypeVar("T")

NOW = 1_761_400_000_000


def _transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as conn:
                return await body(conn)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _create(settings: Settings, url: str, name: str, cookie: str = "c") -> WalletRow:
    return _transaction(
        settings,
        url,
        lambda conn: wallets.create_wallet(
            conn,
            name=name,
            cookie_hash=wallet_codes.cookie_hash(f"{cookie}-{name.strip()}"),
            now_ms=NOW,
        ),
    )


def _rows(settings: Settings, url: str, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async def body(conn: AsyncConnection) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in await conn.execute(text(sql), params)]

    return _transaction(settings, url, body)


def test_a_wallet_is_created_and_found_by_each_of_its_keys(
    settings: Settings, database_url: str
) -> None:
    created = _create(settings, database_url, "  Jan ", cookie="phone")

    assert created.name == "Jan"
    assert wallet_codes.normalise_short_code(created.short_code) == created.short_code
    assert created.created_at.timestamp() * 1000 == NOW

    async def find(conn: AsyncConnection) -> list[WalletRow | None]:
        return [
            await wallets.get_by_cookie_hash(conn, wallet_codes.cookie_hash("phone-Jan")),
            await wallets.get_by_qr_token(conn, created.qr_token),
            await wallets.get_by_short_code(conn, created.short_code),
            await wallets.get(conn, created.wallet_id),
        ]

    assert _transaction(settings, database_url, find) == [created] * 4


def test_only_the_cookie_hash_is_stored(settings: Settings, database_url: str) -> None:
    """AC12."""
    _create(settings, database_url, "Jan", cookie="phone")

    ((stored,),) = _rows(settings, database_url, "SELECT cookie_hash FROM wallet")

    assert stored == wallet_codes.cookie_hash("phone-Jan")
    assert "phone" not in stored


@pytest.mark.parametrize("taken_as", ["jan", "JAN", " Jan "])
def test_a_taken_name_is_refused_with_suggestions(
    settings: Settings, database_url: str, taken_as: str
) -> None:
    """AC4: compared trimmed and case-folded; nothing written."""
    _create(settings, database_url, "Jan")
    _create(settings, database_url, "Jan 2")

    with pytest.raises(NameTaken) as refused:
        _create(settings, database_url, taken_as)

    expected = [f"{taken_as.strip()} {n}" for n in (3, 4, 5)]
    assert refused.value.extra == {"suggestions": expected}
    assert _rows(settings, database_url, "SELECT count(*) FROM wallet") == [(2,)]


def test_two_concurrent_creates_of_one_name_make_one_wallet(
    settings: Settings, database_url: str
) -> None:
    """AC5: the unique index lets exactly one insert win."""

    async def body() -> list[Any]:
        engine = create_engine(settings.model_copy(update={"database_url": database_url}))
        try:

            async def one(cookie: str) -> WalletRow:
                async with engine.begin() as conn:
                    row = await wallets.create_wallet(
                        conn, name="Jan", cookie_hash=cookie, now_ms=NOW
                    )
                    # Hold the transaction open so the other insert has to wait on it.
                    await conn.execute(text("SELECT pg_sleep(0.2)"))
                    return row

            return list(await asyncio.gather(one("a"), one("b"), return_exceptions=True))
        finally:
            await engine.dispose()

    outcomes = asyncio.run(body())

    assert sorted(type(o).__name__ for o in outcomes) == ["NameTaken", "WalletRow"], outcomes
    assert _rows(settings, database_url, "SELECT count(*) FROM wallet") == [(1,)]


def test_a_colliding_short_code_is_drawn_again(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD5: the unique index catches it, and a savepoint retries."""
    first = _create(settings, database_url, "Jan")
    codes = iter([first.short_code, first.short_code, "ABCDEFGH"])
    monkeypatch.setattr(wallet_codes, "new_short_code", lambda: next(codes))

    second = _create(settings, database_url, "Piet")

    assert second.short_code == "ABCDEFGH"


def test_codes_that_always_collide_give_up(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _create(settings, database_url, "Jan")
    monkeypatch.setattr(wallet_codes, "new_short_code", lambda: first.short_code)

    with pytest.raises(Exception, match="wallet_short_code"):
        _create(settings, database_url, "Piet")


def _entry(
    settings: Settings, url: str, wallet_id: int, kind: wallets.EntryKind, amount: int, **kw: Any
) -> wallets.EntryRow:
    return _transaction(
        settings,
        url,
        lambda conn: wallets.insert_entry(
            conn, wallet_id=wallet_id, kind=kind, amount_cents=amount, now_ms=NOW, **kw
        ),
    )


def _balance(settings: Settings, url: str, wallet_id: int) -> int:
    return _transaction(settings, url, lambda conn: wallets.balance(conn, wallet_id))


def test_the_balance_is_the_sum_of_the_entries(settings: Settings, database_url: str) -> None:
    """SD9."""
    wallet = _create(settings, database_url, "Jan")
    assert _balance(settings, database_url, wallet.wallet_id) == 0

    topup = _entry(settings, database_url, wallet.wallet_id, "topup", 1500)
    _entry(settings, database_url, wallet.wallet_id, "topup", 2000)
    _entry(
        settings,
        database_url,
        wallet.wallet_id,
        "reversal",
        -1500,
        reverses_entry_id=topup.entry_id,
    )

    assert _balance(settings, database_url, wallet.wallet_id) == 2000


def _live_run(settings: Settings, url: str) -> int:
    ((run_id,),) = _rows(
        settings,
        url,
        "INSERT INTO run (name, status, run_seed, params) VALUES ('Vrijmibo', 'live', 1, '{}') "
        "RETURNING run_id",
    )
    return int(run_id)


def test_delete_writes_a_closing_entry_blanks_the_row_and_frees_the_name(
    settings: Settings, database_url: str
) -> None:
    """AC29, AC47: a closing -3500 with the live run, every identifying column NULL."""
    run_id = _live_run(settings, database_url)
    wallet = _create(settings, database_url, "Jan")
    _entry(settings, database_url, wallet.wallet_id, "topup", 3500, run_id=run_id)

    _transaction(
        settings,
        database_url,
        lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=NOW + 5_000),
    )

    entries = _rows(
        settings,
        database_url,
        "SELECT kind, amount_cents, run_id FROM wallet_entry ORDER BY entry_id",
    )
    assert entries == [("topup", 3500, run_id), ("closing", -3500, run_id)]
    ((row),) = _rows(
        settings,
        database_url,
        "SELECT name, name_key, qr_token, short_code, cookie_hash, "
        "extract(epoch FROM deleted_at) * 1000 FROM wallet",
    )
    assert row[:5] == (None,) * 5
    assert row[5] == NOW + 5_000
    assert _balance(settings, database_url, wallet.wallet_id) == 0
    assert _create(settings, database_url, "jan").name == "jan"


def test_the_per_run_topups_are_unchanged_by_a_delete(
    settings: Settings, database_url: str
) -> None:
    """AC32 (repository half): the closing entry is not a top-up."""
    run_id = _live_run(settings, database_url)
    wallet = _create(settings, database_url, "Jan")
    _entry(settings, database_url, wallet.wallet_id, "topup", 3500, run_id=run_id)
    totals = (
        "SELECT sum(amount_cents) FROM wallet_entry "
        "WHERE kind IN ('topup', 'reversal') AND run_id = :r"
    )
    before = _rows(settings, database_url, totals, r=run_id)

    _transaction(
        settings,
        database_url,
        lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=NOW),
    )

    assert _rows(settings, database_url, totals, r=run_id) == before == [(3500,)]


def test_delete_with_nothing_left_writes_no_entry(settings: Settings, database_url: str) -> None:
    wallet = _create(settings, database_url, "Jan")

    _transaction(
        settings,
        database_url,
        lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=NOW),
    )

    assert _rows(settings, database_url, "SELECT count(*) FROM wallet_entry") == [(0,)]


def test_a_deleted_wallet_is_found_by_nothing_and_cannot_be_deleted_twice(
    settings: Settings, database_url: str
) -> None:
    wallet = _create(settings, database_url, "Jan", cookie="phone")
    _transaction(
        settings,
        database_url,
        lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=NOW),
    )

    async def find(conn: AsyncConnection) -> list[WalletRow | None]:
        return [
            await wallets.get_by_cookie_hash(conn, wallet_codes.cookie_hash("phone-Jan")),
            await wallets.get_by_qr_token(conn, wallet.qr_token),
            await wallets.get_by_short_code(conn, wallet.short_code),
            await wallets.lock_wallet(conn, wallet.wallet_id),
        ]

    assert _transaction(settings, database_url, find) == [None] * 4
    for action in (
        lambda conn: wallets.get(conn, wallet.wallet_id),
        lambda conn: wallets.delete_wallet(conn, wallet.wallet_id, now_ms=NOW),
        lambda conn: wallets.replace_codes(conn, wallet.wallet_id),
    ):
        with pytest.raises(WalletNotFound):
            _transaction(settings, database_url, action)


def test_new_codes_replace_the_old_ones(settings: Settings, database_url: str) -> None:
    """SD14: the old token and code stop working at once; the cookie does not change."""
    wallet = _create(settings, database_url, "Jan", cookie="phone")

    renewed = _transaction(
        settings, database_url, lambda conn: wallets.replace_codes(conn, wallet.wallet_id)
    )

    async def find(conn: AsyncConnection) -> list[WalletRow | None]:
        return [
            await wallets.get_by_qr_token(conn, wallet.qr_token),
            await wallets.get_by_short_code(conn, wallet.short_code),
            await wallets.get_by_qr_token(conn, renewed.qr_token),
            await wallets.get_by_cookie_hash(conn, wallet_codes.cookie_hash("phone-Jan")),
        ]

    assert renewed.qr_token != wallet.qr_token
    assert renewed.short_code != wallet.short_code
    assert _transaction(settings, database_url, find) == [None, None, renewed, renewed]


def test_settings_default_until_written(settings: Settings, database_url: str) -> None:
    """SD6, SD15: no row is sign-up closed, 30 days, 12 months."""
    assert _transaction(settings, database_url, wallets.get_settings) == WalletSettingsRow(
        None, 30, 12
    )

    for written in (WalletSettingsRow("BORREL", 7, 3), WalletSettingsRow(None, 365, 60)):
        _transaction(settings, database_url, partial(wallets.put_settings, settings=written))
        assert _transaction(settings, database_url, wallets.get_settings) == written

    assert _rows(settings, database_url, "SELECT count(*) FROM wallet_settings") == [(1,)]


def test_taken_name_keys_escape_like_wildcards(settings: Settings, database_url: str) -> None:
    for name in ("50% korting", "50x korting", "a_b", "axb"):
        _create(settings, database_url, name)

    async def keys(conn: AsyncConnection) -> list[set[str]]:
        return [
            await wallets.taken_name_keys(conn, "50%"),
            await wallets.taken_name_keys(conn, "a_"),
        ]

    assert _transaction(settings, database_url, keys) == [{"50% korting"}, {"a_b"}]

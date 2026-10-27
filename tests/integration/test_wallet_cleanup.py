"""The automatic wallet clean-up (B-05 T10: SD15, SD23; AC31, AC44; plan PD11, PD19).

Times are the app clock's: every wallet and entry is written at a `now_ms`
relative to the `FakeClock` the sweep reads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.db.wallets import WalletRow, WalletSettingsRow
from app.runtime import wallets as actions
from app.runtime.boot import start_runtime
from app.runtime.clock import AppClock
from app.runtime.wallet_cleanup import CLEANUP_INTERVAL_MS, run_cleanup, sweep
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000  # 2025-10-01T10:00:00Z
DAY = 24 * 3600 * 1000

T = TypeVar("T")


def _run(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _wallet(engine: AsyncEngine, name: str, created_ms: int) -> WalletRow:
    async with engine.begin() as conn:
        return await wallets.create_wallet(
            conn, name=name, cookie_hash=f"h-{name}", now_ms=created_ms
        )


async def _top_up(engine: AsyncEngine, wallet: WalletRow, amount: int, at_ms: int) -> None:
    async with engine.begin() as conn:
        await wallets.insert_entry(
            conn, wallet_id=wallet.wallet_id, kind="topup", amount_cents=amount, now_ms=at_ms
        )


async def _live_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT name FROM wallet WHERE deleted_at IS NULL ORDER BY name")
        )
        return [str(row[0]) for row in rows]


async def _rows(engine: AsyncEngine, sql: str) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        return [tuple(row) for row in await conn.execute(text(sql))]


def test_an_unfunded_wallet_goes_after_thirty_days(settings: Settings, database_url: str) -> None:
    """AC31: no entry at all and older than the unfunded period."""

    async def body(engine: AsyncEngine) -> tuple[int, list[str]]:
        await _wallet(engine, "Oud", T0 - 31 * DAY)
        await _wallet(engine, "Jong", T0 - 29 * DAY)
        return await sweep(engine, now_ms=T0), await _live_names(engine)

    assert _run(settings, database_url, body) == (1, ["Jong"])


def test_a_funded_wallet_goes_after_twelve_months_without_an_entry(
    settings: Settings, database_url: str
) -> None:
    """AC31: the newest entry decides; the deleted wallet gets its closing entry (SD15)."""

    async def body(engine: AsyncEngine) -> tuple[Any, ...]:
        stale = await _wallet(engine, "Stil", T0 - 500 * DAY)
        await _top_up(engine, stale, 2500, T0 - 400 * DAY)
        await _top_up(engine, stale, 1000, T0 - 396 * DAY)  # 13 months ago
        recent = await _wallet(engine, "Recent", T0 - 500 * DAY)
        await _top_up(engine, recent, 1500, T0 - 335 * DAY)  # 11 months ago
        count = await sweep(engine, now_ms=T0)
        closing = await _rows(
            engine, "SELECT wallet_id, amount_cents FROM wallet_entry WHERE kind = 'closing'"
        )
        return count, await _live_names(engine), closing, stale.wallet_id

    count, live, closing, stale_id = _run(settings, database_url, body)

    assert (count, live) == (1, ["Recent"])
    assert closing == [(stale_id, -3500)]


def test_a_sweep_closing_entry_carries_no_run(settings: Settings, database_url: str) -> None:
    """/review R3: a closing entry with the live run would key-share lock that run's
    row until the sweep commits, so a config write under the state lock (`FOR UPDATE`
    on it) would wait for the whole sweep. A closing entry counts towards no borrel.
    """

    async def body(engine: AsyncEngine) -> list[tuple[Any, ...]]:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO run (name, status, run_seed, params)"
                    " VALUES ('Vrijmibo', 'live', 1, '{}')"
                )
            )
        stale = await _wallet(engine, "Stil", T0 - 500 * DAY)
        await _top_up(engine, stale, 2500, T0 - 400 * DAY)
        await sweep(engine, now_ms=T0)
        return await _rows(engine, "SELECT run_id FROM wallet_entry WHERE kind = 'closing'")

    assert _run(settings, database_url, body) == [(None,)]


def test_an_inactive_wallet_in_debt_is_swept_writing_the_debt_off(
    settings: Settings, database_url: str
) -> None:
    """B-06 AC27, SD8: at -350 after the inactive period, a closing of +350 and no run."""

    async def body(engine: AsyncEngine) -> tuple[Any, ...]:
        debtor = await _wallet(engine, "Rood", T0 - 500 * DAY)
        await _top_up(engine, debtor, 500, T0 - 400 * DAY)
        async with engine.begin() as conn:
            await wallets.insert_entry(
                conn,
                wallet_id=debtor.wallet_id,
                kind="payment",
                amount_cents=-850,
                now_ms=T0 - 399 * DAY,
            )
        count = await sweep(engine, now_ms=T0)
        closing = await _rows(
            engine, "SELECT amount_cents, run_id FROM wallet_entry WHERE kind = 'closing'"
        )
        total = await _rows(engine, "SELECT sum(amount_cents) FROM wallet_entry")
        return count, await _live_names(engine), closing, total

    assert _run(settings, database_url, body) == (1, [], [(350, None)], [(0,)])


def test_a_wallet_older_than_the_months_without_any_entry_goes_too(
    settings: Settings, database_url: str
) -> None:
    """PD19: with no entry, its creation is the last activity."""

    async def body(engine: AsyncEngine) -> list[str]:
        async with engine.begin() as conn:
            await wallets.put_settings(conn, WalletSettingsRow(None, 365, 1))
        await _wallet(engine, "Maand", T0 - 40 * DAY)
        await sweep(engine, now_ms=T0)
        return await _live_names(engine)

    assert _run(settings, database_url, body) == []


def test_opening_the_player_page_is_not_activity(settings: Settings, database_url: str) -> None:
    """AC31: what `GET /api/wallet` reads writes nothing, so the wallet still goes."""

    async def body(engine: AsyncEngine) -> list[str]:
        wallet = await _wallet(engine, "Kijker", T0 - 31 * DAY)
        async with engine.connect() as conn:
            found = await wallets.get_by_cookie_hash(conn, "h-Kijker")
        assert found == wallet
        await actions.player_wallet(engine, wallet)
        await sweep(engine, now_ms=T0)
        return await _live_names(engine)

    assert _run(settings, database_url, body) == []


def test_the_periods_are_the_settings(settings: Settings, database_url: str) -> None:
    """AC31, AC33: a 1-day unfunded period is obeyed."""

    async def body(engine: AsyncEngine) -> list[str]:
        async with engine.begin() as conn:
            await wallets.put_settings(conn, WalletSettingsRow(None, 1, 12))
        await _wallet(engine, "Gisteren", T0 - 2 * DAY)
        await _wallet(engine, "Vandaag", T0 - DAY // 2)
        await sweep(engine, now_ms=T0)
        return await _live_names(engine)

    assert _run(settings, database_url, body) == ["Vandaag"]


# Serial (SD3): asserts a deadline: `wait_for(..., 5)` is "skipped, not waited for".
@pytest.mark.serial
def test_a_wallet_another_transaction_holds_is_skipped_not_waited_for(
    settings: Settings, database_url: str
) -> None:
    """PD11: `SKIP LOCKED`; the next sweep takes it."""

    async def body(engine: AsyncEngine) -> tuple[int, int]:
        wallet = await _wallet(engine, "Bezet", T0 - 31 * DAY)
        async with engine.begin() as holding:
            await wallets.lock_wallet(holding, wallet.wallet_id)
            skipped = await asyncio.wait_for(sweep(engine, now_ms=T0), timeout=5)
        return skipped, await sweep(engine, now_ms=T0)

    assert _run(settings, database_url, body) == (0, 1)


def test_a_wallet_touched_since_its_candidacy_is_kept(
    settings: Settings, database_url: str
) -> None:
    """PD11: the re-check after the lock sees an entry committed in between."""

    async def body(engine: AsyncEngine) -> list[int]:
        wallet = await _wallet(engine, "Net", T0 - 31 * DAY)
        async with engine.connect() as conn:
            candidates = await wallets.expired(conn, now_ms=T0, settings=WalletSettingsRow())
        await _top_up(engine, wallet, 1000, T0)
        async with engine.connect() as conn:
            return await wallets.expired(
                conn, now_ms=T0, settings=WalletSettingsRow(), among=candidates
            )

    assert _run(settings, database_url, body) == []


async def _until(check: Callable[[], Awaitable[bool]], timeout_s: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.05)
    return False


def _asleep(clock: FakeClock) -> Callable[[], Awaitable[bool]]:
    """The loop is waiting on `clock` for its next sweep."""

    async def check() -> bool:
        return clock.sleepers == 1

    return check


@pytest.mark.parametrize("draining", [False, True])
def test_the_loop_sweeps_every_24_hours_and_not_while_draining(
    settings: Settings, database_url: str, draining: bool
) -> None:
    """AC31, AC44."""

    async def body(engine: AsyncEngine) -> tuple[list[str], list[str]]:
        clock = FakeClock(T0)
        task = asyncio.get_running_loop().create_task(
            run_cleanup(engine=engine, clock=clock, draining=lambda: draining)
        )
        try:
            await _until(_asleep(clock))
            await _wallet(engine, "Oud", T0 - 30 * DAY)  # 30 days old: kept until a day passes
            clock.advance(CLEANUP_INTERVAL_MS - 1)
            await asyncio.sleep(0.2)
            before = await _live_names(engine)
            clock.advance(1)

            async def swept() -> bool:
                return await _live_names(engine) == []

            await _until(swept, timeout_s=1.0 if draining else 5.0)
            return before, await _live_names(engine)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    before, after = _run(settings, database_url, body)

    assert before == ["Oud"]
    assert after == (["Oud"] if draining else [])


def test_a_second_day_sweeps_again(settings: Settings, database_url: str) -> None:
    async def body(engine: AsyncEngine) -> list[str]:
        clock = FakeClock(T0)
        task = asyncio.get_running_loop().create_task(
            run_cleanup(engine=engine, clock=clock, draining=lambda: False)
        )
        try:
            await _until(_asleep(clock))
            clock.advance(CLEANUP_INTERVAL_MS)
            await _until(_asleep(clock))
            await _wallet(engine, "Later", T0 - 30 * DAY)
            clock.advance(CLEANUP_INTERVAL_MS)

            async def swept() -> bool:
                return await _live_names(engine) == []

            await _until(swept)
            return await _live_names(engine)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert _run(settings, database_url, body) == []


def test_the_boot_sweep_writes_off_an_inactive_wallet_in_debt(
    settings: Settings, database_url: str
) -> None:
    """B-06 T18: AC27, SD8 end to end -- the sweep the boot runs, before the app is ready."""

    async def body(engine: AsyncEngine) -> tuple[list[str], list[tuple[Any, ...]]]:
        debtor = await _wallet(engine, "Rood", T0 - 500 * DAY)
        await _top_up(engine, debtor, 500, T0 - 400 * DAY)
        async with engine.begin() as conn:
            await wallets.insert_entry(
                conn,
                wallet_id=debtor.wallet_id,
                kind="payment",
                amount_cents=-850,
                now_ms=T0 - 399 * DAY,
            )
        await _wallet(engine, "Nieuw", T0 - DAY)
        app = FastAPI()
        scoped = settings.model_copy(update={"database_url": database_url})
        async with start_runtime(app, scoped, clock=AppClock(FakeClock(T0)), run_migrations=False):
            assert app.state.ready
            ledger = await _rows(
                engine,
                "SELECT kind, amount_cents, run_id, sum(amount_cents) OVER () FROM wallet_entry"
                f" WHERE wallet_id = {debtor.wallet_id} ORDER BY entry_id",
            )
            return await _live_names(engine), ledger

    names, ledger = _run(settings, database_url, body)
    assert names == ["Nieuw"]
    assert ledger == [
        ("topup", 500, None, 0),
        ("payment", -850, None, 0),
        ("closing", 350, None, 0),
    ]


def test_boot_runs_one_sweep(settings: Settings, database_url: str) -> None:
    """AC31: at boot, before the app is ready."""

    async def body(engine: AsyncEngine) -> list[str]:
        await _wallet(engine, "Vergeten", T0 - 31 * DAY)
        await _wallet(engine, "Nieuw", T0 - DAY)
        app = FastAPI()
        scoped = settings.model_copy(update={"database_url": database_url})
        async with start_runtime(app, scoped, clock=AppClock(FakeClock(T0)), run_migrations=False):
            assert app.state.ready
            return await _live_names(engine)

    assert _run(settings, database_url, body) == ["Nieuw"]

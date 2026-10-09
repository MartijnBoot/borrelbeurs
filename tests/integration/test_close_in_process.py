"""`close_in_process` across a restart (Phase 7 T6: AC6, AC37; SD2, SD14; PD4).

The runtime is booted with `start_runtime`, as `test_boot.py` does: a close
ends the run for good, so the next boot holds no run; a shutdown that never
closed leaves the run live, and the next boot rehydrates it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.runtime.boot import start_runtime
from app.runtime.close import close_in_process
from app.runtime.holder import PersistenceUnavailable
from exchange import Params
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _settings(settings: Settings, url: str) -> Settings:
    return settings.model_copy(update={"database_url": url})


async def _live(engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        run_id = await create_draft_run(
            conn, name="Vrijmibo", params=Params(step_quant=0.1), run_seed=7
        )
        await add_drink(
            conn,
            run_id,
            name="Bier",
            slot=0,
            p_min_cents=150,
            p0_cents=260,
            p_max_cents=500,
            a=1.0,
            d=0.1,
            s0=1.0,
            c=0.1,
            bar_price_cents=260,
        )
    await go_live(engine, run_id, now_ms=T0)
    return run_id


async def _rows(engine: AsyncEngine, run_id: int) -> list[Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT row_to_json(r)::text FROM run r WHERE run_id = :r"
                " UNION ALL SELECT count(*)::text FROM price_tick WHERE run_id = :r"
                " UNION ALL SELECT row_to_json(e)::text FROM engine_state e WHERE run_id = :r"
            ),
            {"r": run_id},
        )
        return [row[0] for row in result]


def test_a_closed_run_is_not_rehydrated_and_stays_as_it_was(on: str, settings: Settings) -> None:
    """AC6: the restart boots an empty holder; the ended run is unchanged by it."""

    async def scenario() -> tuple[bool, str, list[Any], list[Any]]:
        engine = create_engine(_settings(settings, on))
        try:
            run_id = await _live(engine)
            app = FastAPI()
            app.state.clock = clock = FakeClock(T0 + 1_000)  # `create_app` sets it in production
            async with start_runtime(
                app, _settings(settings, on), clock=clock, run_migrations=False
            ):
                await close_in_process(app.state, run_id, confirm_name="Vrijmibo", author="t")
            before = await _rows(engine, run_id)
            again = FastAPI()
            async with start_runtime(
                again, _settings(settings, on), clock=FakeClock(T0 + 9_000), run_migrations=False
            ):
                empty = again.state.holder.is_empty
            async with engine.connect() as conn:
                status = str(
                    (
                        await conn.execute(
                            text("SELECT status FROM run WHERE run_id = :r"), {"r": run_id}
                        )
                    ).scalar_one()
                )
            return empty, status, before, await _rows(engine, run_id)
        finally:
            await engine.dispose()

    empty, status, before, after = asyncio.run(scenario())
    assert empty
    assert status == "ended"
    assert after == before


def test_a_shutdown_without_a_close_leaves_the_run_live_and_rehydrates_it(
    on: str, settings: Settings
) -> None:
    """AC37, SD14: "Sluit app" is not close."""

    async def scenario() -> tuple[str, int | None]:
        engine = create_engine(_settings(settings, on))
        try:
            run_id = await _live(engine)
            first = FastAPI()
            async with start_runtime(
                first, _settings(settings, on), clock=FakeClock(T0 + 1_000), run_migrations=False
            ):
                assert first.state.holder.run_id == run_id
            async with engine.connect() as conn:
                status = str(
                    (
                        await conn.execute(
                            text("SELECT status FROM run WHERE run_id = :r"), {"r": run_id}
                        )
                    ).scalar_one()
                )
            again = FastAPI()
            async with start_runtime(
                again, _settings(settings, on), clock=FakeClock(T0 + 9_000), run_migrations=False
            ):
                return status, again.state.holder.run_id
        finally:
            await engine.dispose()

    status, held = asyncio.run(scenario())
    assert status == "live"
    assert held is not None


def test_a_close_whose_commit_fails_leaves_everything_live(
    on: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD4: a failed commit changes no memory and tells no client."""
    import app.runtime.close as close_module

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("connection reset")

    monkeypatch.setattr(close_module, "close_run", broken)

    async def scenario() -> tuple[bool, int, str]:
        engine = create_engine(_settings(settings, on))
        try:
            run_id = await _live(engine)
            app = FastAPI()
            app.state.clock = clock = FakeClock(T0 + 1_000)  # `create_app` sets it in production
            async with start_runtime(
                app, _settings(settings, on), clock=clock, run_migrations=False
            ):
                seq = app.state.hub.seq
                with pytest.raises(PersistenceUnavailable):
                    await close_in_process(app.state, run_id, confirm_name="Vrijmibo", author="t")
                held = app.state.holder.run_id == run_id
                moved = app.state.hub.seq - seq
            async with engine.connect() as conn:
                status = str(
                    (
                        await conn.execute(
                            text("SELECT status FROM run WHERE run_id = :r"), {"r": run_id}
                        )
                    ).scalar_one()
                )
            return held, moved, status
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == (True, 0, "live")

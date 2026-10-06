"""`python -m app.cli.runs go-live` (Phase 3 T9: SD16)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.cli.runs import main
from app.core.config import Settings, get_settings
from app.db.advisory_lock import acquire, release
from app.db.runs import add_drink, create_draft_run
from app.db.session import create_engine
from exchange import Params


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """`main`'s environment, pointed at the per-test scratch database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


def _draft(settings: Settings, url: str, *, drinks: bool = True) -> int:
    async def scenario() -> int:
        engine = _engine(settings, url)
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(
                    conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
                )
                if drinks:
                    await add_drink(
                        conn,
                        run_id,
                        name="Bier",
                        slot=0,
                        p_min_cents=150,
                        p0_cents=260,
                        p_max_cents=500,
                        a=0.0,
                        d=0.0,
                        s0=0.0,
                        c=0.0,
                        bar_price_cents=260,
                    )
            return run_id
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def _status(settings: Settings, url: str, run_id: int) -> tuple[str, int]:
    async def scenario() -> tuple[str, int]:
        engine = _engine(settings, url)
        try:
            async with engine.connect() as conn:
                status: str = (
                    await conn.execute(
                        text("SELECT status FROM run WHERE run_id = :r"), {"r": run_id}
                    )
                ).scalar_one()
                ticks: int = (
                    await conn.execute(
                        text("SELECT count(*) FROM price_tick WHERE run_id = :r"), {"r": run_id}
                    )
                ).scalar_one()
                return str(status), int(ticks)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_go_live_makes_a_draft_run_live(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _draft(settings, scratch)

    assert main(["go-live", str(run_id)]) == 0

    assert f"run {run_id} is live" in capsys.readouterr().out
    assert _status(settings, scratch, run_id) == ("live", 1)


def test_go_live_is_refused_while_the_app_holds_the_lock(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """SD16: the lock is held, so nothing is written and the operator is told why."""
    run_id = _draft(settings, scratch)
    held: dict[str, object] = {}

    async def hold_and_try() -> int:
        engine = _engine(settings, scratch)
        try:
            conn = await acquire(engine)
            assert conn is not None
            try:
                return await asyncio.to_thread(main, ["go-live", str(run_id)])
            finally:
                await release(conn)
        finally:
            await engine.dispose()

    held["exit"] = asyncio.run(hold_and_try())

    assert held["exit"] == 2
    assert "the app is running; stop it first" in capsys.readouterr().err
    assert _status(settings, scratch, run_id) == ("draft", 0)


@pytest.mark.parametrize(
    ("setup", "message"),
    [("no-drinks", "has no drinks"), ("already-live", "not draft"), ("unknown", "no run")],
)
def test_a_run_that_cannot_go_live_exits_1_naming_why(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str], setup: str, message: str
) -> None:
    if setup == "no-drinks":
        run_id = _draft(settings, scratch, drinks=False)
    elif setup == "already-live":
        run_id = _draft(settings, scratch)
        assert main(["go-live", str(run_id)]) == 0
        capsys.readouterr()
    else:
        run_id = 999_999

    assert main(["go-live", str(run_id)]) == 1

    assert message in capsys.readouterr().err


def test_a_second_live_run_is_refused(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _draft(settings, scratch)
    second = _draft(settings, scratch)
    assert main(["go-live", str(first)]) == 0

    assert main(["go-live", str(second)]) == 1

    assert "already live" in capsys.readouterr().err
    assert _status(settings, scratch, second) == ("draft", 0)

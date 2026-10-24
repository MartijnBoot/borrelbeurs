"""A profile survives a restart, and a run made from it goes live with its values (B-04 T11).

AC26 and the spec's Verification > Integration: a create with a profile and a load
onto a draft, each then taken live and brought up from the database as boot
brings it up (`rehydrate`, `MarketHolder.from_rehydrated`, as
`test_config_live.py`), running on the profile's values. And a fresh app against
the same database lists the profile as it was committed.

These tests change no source: one failing means the code does not do what SD4
or SD15 say.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import format_key, hash_secret, mint_secret
from app.core.config import Settings, get_settings
from app.db.keys import create_key, set_secret_hash
from app.db.runs import DEFAULT_PARAMS, add_drink, create_run, delete_run, go_live
from app.db.session import create_engine
from app.main import create_app
from app.runtime.config import ConfigPatch, load_profile_onto_draft, write_draft_config
from app.runtime.config_patch import profile_settings
from app.runtime.holder import MarketHolder
from app.runtime.profiles import save_profile_from_run
from app.runtime.rehydrate import RehydratedRun, rehydrate
from tests.integration.test_config_live import _tick
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000
BASE_URL = "https://testserver"

# The 22 tuned away from `DEFAULT_PARAMS`, Kaarsbreedte included.
WILD = ConfigPatch.model_validate(
    {
        "candle_interval_s": 30,
        "params": {"bm_sigma_y": 0.5, "eta": 0.9, "y_clip": 4.0, "idle_strength": 3.0},
    }
)


def _run(settings: Settings, url: str, body: Any) -> Any:
    async def scenario() -> Any:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _wild_profile(engine: AsyncEngine) -> dict[str, Any]:
    """A profile saved from a draft tuned wild; the draft is deleted. Its stored 22."""
    source = await create_run(engine, name="Proef", author="seed")
    await write_draft_config(engine, source, WILD, author="seed")
    row, _ = await save_profile_from_run(
        engine, name="Wilde beurs", run_id=source, overwrite=False, author="seed"
    )
    await delete_run(engine, source, confirm_name="Proef")
    assert row.settings["candle_interval_s"] == 30
    assert row.settings != profile_settings(DEFAULT_PARAMS, 60_000)
    return row.settings


async def _stock(engine: AsyncEngine, run_id: int) -> None:
    async with engine.begin() as conn:
        for slot, name in enumerate(("Bier", "Wijn", "Fris")):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=150,
                p0_cents=260,
                p_max_cents=500,
                a=1.0,
                d=0.1,
                s0=1.0,
                c=0.1,
                bar_price_cents=260,
            )


async def _live_from_boot(engine: AsyncEngine, run_id: int) -> tuple[RehydratedRun, int, int]:
    """`run_id` taken live, rehydrated as boot does, and ticked once: the run, versions."""
    await _stock(engine, run_id)
    await go_live(engine, run_id, now_ms=T0, author="seed")
    run = await rehydrate(engine, now_ms=T0)
    assert isinstance(run, RehydratedRun)
    clock = FakeClock(T0)
    holder = MarketHolder.from_rehydrated(run, engine=engine, clock=clock, sink=lambda _: None)
    before = run.state.version
    after = (await _tick(engine, holder, clock)).version
    return run, before, after


def _assert_on_profile(run: RehydratedRun, stored: dict[str, Any], before: int, after: int) -> None:
    assert profile_settings(run.spec.params, run.candle_interval_ms) == stored
    assert run.candle_interval_ms == 30_000
    assert after == before + 1


def test_a_borrel_created_from_a_profile_goes_live_with_its_values(
    settings: Settings, database_url: str
) -> None:
    """AC26 (create): `spec.params` holds the profile's 21, Kaarsbreedte 30 s, and it ticks."""

    async def body(engine: AsyncEngine) -> tuple[Any, ...]:
        stored = await _wild_profile(engine)
        async with engine.connect() as conn:
            profile_id: int
            (profile_id,) = (
                await conn.execute(text("SELECT profile_id FROM settings_profile"))
            ).scalars()
        run_id = await create_run(engine, name="Borrel", author="seed", profile_id=profile_id)
        return stored, *await _live_from_boot(engine, run_id)

    stored, run, before, after = _run(settings, database_url, body)

    _assert_on_profile(run, stored, before, after)


def test_a_draft_loaded_with_a_profile_goes_live_with_its_values(
    settings: Settings, database_url: str
) -> None:
    """AC26 (load): a draft from the defaults, a load, go-live, the same values."""

    async def body(engine: AsyncEngine) -> tuple[Any, ...]:
        stored = await _wild_profile(engine)
        async with engine.connect() as conn:
            profile_id: int
            (profile_id,) = (
                await conn.execute(text("SELECT profile_id FROM settings_profile"))
            ).scalars()
        run_id = await create_run(engine, name="Borrel", author="seed")
        await load_profile_onto_draft(engine, run_id, profile_id, author="seed")
        return stored, *await _live_from_boot(engine, run_id)

    stored, run, before, after = _run(settings, database_url, body)

    _assert_on_profile(run, stored, before, after)


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """The app's settings on the scratch database, as `tests/api/conftest.py` does."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def test_a_fresh_app_lists_the_profile_as_committed(settings: Settings, on: str) -> None:
    """AC26 (survives): a restart is a new process on the same database."""

    async def seed(engine: AsyncEngine) -> tuple[dict[str, Any], str]:
        stored = await _wild_profile(engine)
        async with engine.begin() as conn:
            key_id = await create_key(conn, label="Bestuur", role="admin", secret_hash="pending")
            secret = mint_secret()
            await set_secret_hash(conn, key_id, hash_secret(secret))
        return stored, format_key(key_id, secret)

    stored, key = _run(settings, on, seed)

    app = create_app(clock=FakeClock(T0), run_migrations=False)
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as client:
        assert client.post("/api/auth/login", json={"key": key}).status_code == 200
        listed = client.get("/api/profiles").json()

    async def read(engine: AsyncEngine) -> list[Any]:
        async with engine.connect() as conn:
            return list(
                (await conn.execute(text("SELECT settings FROM settings_profile"))).scalars()
            )

    assert [(p["name"], p["source_run_name"]) for p in listed] == [("Wilde beurs", "Proef")]
    assert _run(settings, on, read) == [stored]

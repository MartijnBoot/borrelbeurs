"""Run and drink repositories against the scratch database (T5).

AC15 (duplicate names), AC12 (set half), SD6 (draft creation), SD14, PD6.
Each scenario opens its own transaction, as a real caller would: the
repositories take a connection and never begin or commit one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db.mapping import DrinkRow
from app.db.runs import (
    DraftExists,
    DuplicateDrinkName,
    LiveRunExists,
    RunSummary,
    active_drinks,
    add_drink,
    all_drinks,
    append_config_revision,
    create_draft_run,
    create_run,
    current_run,
    set_bar_price,
)
from app.db.session import create_engine
from exchange import Params

T = TypeVar("T")


def _transaction(
    settings: Settings, url: str, body: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    """Run `body` in one committed transaction on an engine built the app's way."""

    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            async with engine.begin() as connection:
                return await body(connection)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _bier(connection: AsyncConnection, run_id: int, name: str = "Bier", slot: int = 0) -> int:
    return await add_drink(
        connection,
        run_id,
        name=name,
        slot=slot,
        p_min_cents=150,
        p0_cents=260,
        p_max_cents=500,
        a=0.0,
        d=0.0,
        s0=0.0,
        c=0.0,
        bar_price_cents=260,
    )


async def _draft(connection: AsyncConnection) -> int:
    return await create_draft_run(
        connection, name="Borrel", params=Params(step_quant=0.1), run_seed=7
    )


def test_a_draft_run_stores_its_params_and_seed(settings: Settings, database_url: str) -> None:
    async def body(connection: AsyncConnection) -> tuple[str, int, dict[str, object]]:
        run_id = await _draft(connection)
        row = (
            await connection.execute(
                text("SELECT status, run_seed, params FROM run WHERE run_id = :r"), {"r": run_id}
            )
        ).one()
        return str(row.status), int(row.run_seed), dict(row.params)

    status, seed, params = _transaction(settings, database_url, body)

    assert (status, seed) == ("draft", 7)
    assert Params.from_dict(params) == Params(step_quant=0.1)


def test_a_trimmed_case_insensitive_duplicate_name_is_rejected(
    settings: Settings, database_url: str
) -> None:
    """AC15: `Bier` then ` bier ` collide, and the error names the clash."""

    async def first(connection: AsyncConnection) -> int:
        run_id = await _draft(connection)
        await _bier(connection, run_id)
        return run_id

    run_id = _transaction(settings, database_url, first)

    async def second(connection: AsyncConnection) -> int:
        return await _bier(connection, run_id, name=" bier ", slot=1)

    with pytest.raises(DuplicateDrinkName, match="' bier '") as raised:
        _transaction(settings, database_url, second)
    assert raised.value.status_code == 409


def test_non_ascii_names_fold_the_same_way_on_every_server(
    settings: Settings, database_url: str
) -> None:
    """R4, PD6: `Café` and `CAFÉ` collide even under the compose `--locale=C`."""

    async def body(connection: AsyncConnection) -> None:
        run_id = await _draft(connection)
        await _bier(connection, run_id, name="Café")
        await _bier(connection, run_id, name="CAFÉ", slot=1)

    with pytest.raises(DuplicateDrinkName, match="CAFÉ"):
        _transaction(settings, database_url, body)


def test_a_removed_drinks_name_is_accepted_again(settings: Settings, database_url: str) -> None:
    """AC15: soft removal (a direct UPDATE; the real operation is Phase 6) frees the name."""

    async def body(connection: AsyncConnection) -> list[DrinkRow]:
        run_id = await _draft(connection)
        first = await _bier(connection, run_id)
        await connection.execute(
            text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": first}
        )
        await _bier(connection, run_id, slot=1)
        return await active_drinks(connection, run_id)

    (only,) = _transaction(settings, database_url, body)

    assert (only.name, only.slot) == ("Bier", 1)


def test_the_same_name_in_two_runs_is_accepted(settings: Settings, database_url: str) -> None:
    async def body(connection: AsyncConnection) -> None:
        await _bier(connection, await _draft(connection))
        await _bier(connection, await _draft(connection))

    _transaction(settings, database_url, body)


def test_set_bar_price_persists(settings: Settings, database_url: str) -> None:
    """AC12 (set half)."""

    async def setup(connection: AsyncConnection) -> tuple[int, int]:
        run_id = await _draft(connection)
        return run_id, await _bier(connection, run_id)

    run_id, drink_id = _transaction(settings, database_url, setup)

    async def change(connection: AsyncConnection) -> None:
        await set_bar_price(connection, drink_id, 225)

    _transaction(settings, database_url, change)

    async def read(connection: AsyncConnection) -> list[DrinkRow]:
        return await active_drinks(connection, run_id)

    (drink,) = _transaction(settings, database_url, read)
    assert (drink.drink_id, drink.bar_price_cents) == (drink_id, 225)


def test_set_bar_price_on_an_unknown_drink_raises(settings: Settings, database_url: str) -> None:
    async def body(connection: AsyncConnection) -> None:
        await set_bar_price(connection, 999_999, 225)

    with pytest.raises(LookupError, match="999999"):
        _transaction(settings, database_url, body)


def test_config_revisions_number_from_one(settings: Settings, database_url: str) -> None:
    async def body(connection: AsyncConnection) -> list[int]:
        run_id = await _draft(connection)
        other = await _draft(connection)
        revisions = [
            await append_config_revision(connection, run_id, config={"n": n}, author="test")
            for n in range(3)
        ]
        revisions.append(await append_config_revision(connection, other, config={}, author="test"))
        return revisions

    assert _transaction(settings, database_url, body) == [1, 2, 3, 1]


def test_active_drinks_are_the_non_removed_ones_in_slot_order(
    settings: Settings, database_url: str
) -> None:
    async def body(connection: AsyncConnection) -> list[DrinkRow]:
        run_id = await _draft(connection)
        ids = {
            name: await _bier(connection, run_id, name=name, slot=slot)
            for name, slot in (
                ("Wijn", 4),
                ("Bier", 1),
                ("Fris", 9),
                ("Stelz", 2),
            )
        }
        await connection.execute(
            text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": ids["Fris"]}
        )
        await _bier(connection, await _draft(connection), name="Elders", slot=0)
        return await active_drinks(connection, run_id)

    drinks = _transaction(settings, database_url, body)

    assert [(d.name, d.slot) for d in drinks] == [("Bier", 1), ("Stelz", 2), ("Wijn", 4)]
    assert not any(d.removed for d in drinks)
    assert drinks[0] == DrinkRow(
        drink_id=drinks[0].drink_id,
        slot=1,
        name="Bier",
        p_min_cents=150,
        p0_cents=260,
        p_max_cents=500,
        a=0.0,
        d=0.0,
        s0=0.0,
        c=0.0,
        bar_price_cents=260,
    )


def test_all_drinks_are_every_row_in_slot_order_flagging_the_removed(
    settings: Settings, database_url: str
) -> None:
    """SD15: a removed drink keeps its slot, so the engine's arrays keep their shape."""

    async def body(connection: AsyncConnection) -> list[DrinkRow]:
        run_id = await _draft(connection)
        ids = {
            name: await _bier(connection, run_id, name=name, slot=slot)
            for name, slot in (("Wijn", 4), ("Bier", 1), ("Fris", 9))
        }
        await connection.execute(
            text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": ids["Bier"]}
        )
        await _bier(connection, await _draft(connection), name="Elders", slot=0)
        return await all_drinks(connection, run_id)

    drinks = _transaction(settings, database_url, body)

    assert [(d.name, d.slot, d.removed) for d in drinks] == [
        ("Bier", 1, True),
        ("Wijn", 4, False),
        ("Fris", 9, False),
    ]


def _with_engine(settings: Settings, url: str, body: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def scenario() -> T:
        engine = create_engine(settings.model_copy(update={"database_url": url}))
        try:
            return await body(engine)
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


async def _end(engine: AsyncEngine, run_id: int, status: str = "ended") -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE run SET status = :s WHERE run_id = :r"), {"s": status, "r": run_id}
        )


def test_create_run_takes_params_defaults_and_writes_revision_one(
    settings: Settings, database_url: str
) -> None:
    """Phase 6 SD2, PD6: an empty database gives `Params()`; revision 1 by the author."""

    async def body(engine: AsyncEngine) -> tuple[tuple[Any, ...], list[tuple[Any, ...]]]:
        run_id = await create_run(engine, name="  Vrijmibo ", author="admin key")
        async with engine.connect() as conn:
            run = (
                await conn.execute(
                    text(
                        "SELECT name, status, params, tick_interval_ms, candle_interval_ms,"
                        " quote_grace_versions FROM run WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            ).one()
            revisions = (
                await conn.execute(text("SELECT revision, author, config FROM run_config_revision"))
            ).all()
        return tuple(run), [tuple(r) for r in revisions]

    run, revisions = _with_engine(settings, database_url, body)

    name, status, params, tick, candle, grace = run
    assert (name, status, tick, candle, grace) == ("Vrijmibo", "draft", 1000, 60_000, 2)
    assert Params.from_dict(params) == Params()
    ((revision, author, config),) = revisions
    assert (revision, author) == (1, "admin key")
    assert (config["name"], config["drinks"]) == ("Vrijmibo", [])
    assert Params.from_dict(config["params"]) == Params()


def test_create_run_copies_the_most_recently_created_runs_params(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: AsyncEngine) -> Params:
        for step in (0.1, 0.2):
            async with engine.begin() as conn:
                old = await create_draft_run(
                    conn, name="Oud", params=Params(step_quant=step), run_seed=1
                )
            await _end(engine, old)
        run_id = await create_run(engine, name="Nieuw", author="a")
        async with engine.connect() as conn:
            stored: dict[str, Any] = (
                await conn.execute(text("SELECT params FROM run WHERE run_id = :r"), {"r": run_id})
            ).scalar_one()
        return Params.from_dict(stored)

    assert _with_engine(settings, database_url, body) == Params(step_quant=0.2)


def test_create_run_refuses_while_a_draft_or_a_live_run_exists(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: AsyncEngine) -> tuple[int, Any, int]:
        draft = await create_run(engine, name="Een", author="a")
        with pytest.raises(DraftExists) as refused:
            await create_run(engine, name="Twee", author="a")
        await _end(engine, draft, "live")
        with pytest.raises(LiveRunExists):
            await create_run(engine, name="Drie", author="a")
        async with engine.connect() as conn:
            count = int((await conn.execute(text("SELECT count(*) FROM run"))).scalar_one())
        return draft, refused.value.extra.get("run_id"), count

    draft, carried, count = _with_engine(settings, database_url, body)

    assert carried == draft
    assert count == 1


def test_concurrent_creates_make_exactly_one_draft(settings: Settings, database_url: str) -> None:
    """Choice (b), the user's, 2026-10-06: creation is serialised, with no schema change."""

    async def body(engine: AsyncEngine) -> tuple[list[Any], int]:
        results = await asyncio.gather(
            *(create_run(engine, name=f"Borrel {i}", author="a") for i in range(4)),
            return_exceptions=True,
        )
        async with engine.connect() as conn:
            drafts = int(
                (
                    await conn.execute(text("SELECT count(*) FROM run WHERE status = 'draft'"))
                ).scalar_one()
            )
        return list(results), drafts

    results, drafts = _with_engine(settings, database_url, body)

    assert drafts == 1
    assert sum(isinstance(r, int) for r in results) == 1
    assert sum(isinstance(r, DraftExists) for r in results) == 3


def test_current_run_is_live_over_draft_else_the_newest_draft_else_none(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: AsyncEngine) -> list[RunSummary | None]:
        seen: list[RunSummary | None] = []
        async with engine.connect() as conn:
            seen.append(await current_run(conn))
        async with engine.begin() as conn:
            live = await create_draft_run(conn, name="Live", params=Params(), run_seed=1)
            await create_draft_run(conn, name="Ouder concept", params=Params(), run_seed=1)
            await create_draft_run(conn, name="Concept", params=Params(), run_seed=1)
        await _end(engine, live, "live")
        async with engine.connect() as conn:
            seen.append(await current_run(conn))
        await _end(engine, live)
        async with engine.connect() as conn:
            seen.append(await current_run(conn))
        return seen

    none, live, draft = _with_engine(settings, database_url, body)

    assert none is None
    assert live is not None and (live.name, live.status) == ("Live", "live")
    assert draft is not None and (draft.name, draft.status) == ("Concept", "draft")

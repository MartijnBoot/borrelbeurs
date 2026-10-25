"""Run and drink repositories against the scratch database (T5).

AC15 (duplicate names), AC12 (set half), SD6 (draft creation), SD14, PD6.
Each scenario opens its own transaction, as a real caller would: the
repositories take a connection and never begin or commit one.

B-04 T5: a create with a profile (AC7-AC10, AC15; SD4).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db.mapping import DrinkRow
from app.db.profiles import ProfileNotFound, save_profile
from app.db.runs import (
    DEFAULT_PARAMS,
    DraftExists,
    DuplicateDrinkName,
    LiveRunExists,
    RunNotFound,
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
from app.runtime.config_patch import PROFILE_FIELDS, InvalidConfig, profile_settings
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
    """Phase 6 SD2, PD6: an empty database gives v1's saved settings; revision 1 by the author."""

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
    assert Params.from_dict(params) == DEFAULT_PARAMS
    ((revision, author, config),) = revisions
    assert (revision, author) == (1, "admin key")
    assert (config["name"], config["drinks"]) == ("Vrijmibo", [])
    assert Params.from_dict(config["params"]) == DEFAULT_PARAMS
    # B-04 PD9: revision 1 records Kaarsbreedte on every create.
    assert config["candle_interval_s"] == 60


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


def test_create_run_copies_a_closed_runs_active_drinks_and_params(
    settings: Settings, database_url: str
) -> None:
    """Phase 7 SD4, AC9: active drinks only, new ids, compact slots, the same products."""

    async def body(engine: AsyncEngine) -> tuple[Any, ...]:
        async with engine.begin() as conn:
            source = await create_draft_run(
                conn, name="Vorige", params=Params(step_quant=0.3), run_seed=1
            )
            await _bier(conn, source, "Bier", slot=0)
            wijn = await _bier(conn, source, "Wijn", slot=2)
            await _bier(conn, source, "Fris", slot=3)
            await conn.execute(
                text("UPDATE drink SET removed_at = now() WHERE drink_id = :d"), {"d": wijn}
            )
            await conn.execute(
                text(
                    "UPDATE drink SET p_min_cents = 120, p0_cents = 210, p_max_cents = 450,"
                    " a = 0.5, d = 0.25, s0 = 1.5, c = 0.75, bar_price_cents = 199"
                    " WHERE run_id = :r AND name = 'Fris'"
                ),
                {"r": source},
            )
            await conn.execute(
                text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 1, 'info', 'x')"),
                {"r": source},
            )
            await conn.execute(
                text(
                    "INSERT INTO market_event (run_id, kind, drink_ids, t_start_ms, t_end_ms)"
                    " VALUES (:r, 'crash', '[]', 1, 2)"
                ),
                {"r": source},
            )
        await _end(engine, source)
        async with engine.begin() as conn:
            # The latest run's params, which a copy must not take.
            await create_draft_run(conn, name="Nieuwer", params=Params(step_quant=0.9), run_seed=1)
            await conn.execute(text("UPDATE run SET status = 'ended' WHERE name = 'Nieuwer'"))

        run_id = await create_run(engine, name="Nieuw", author="a", copy_from_run_id=source)

        columns = (
            "slot, name, p_min_cents, p0_cents, p_max_cents, a, d, s0, c, bar_price_cents,"
            " product_id, drink_id, removed_at IS NULL"
        )
        async with engine.connect() as conn:

            async def drinks(run: int) -> list[tuple[Any, ...]]:
                rows = await conn.execute(
                    text(f"SELECT {columns} FROM drink WHERE run_id = :r ORDER BY slot"), {"r": run}
                )
                return [tuple(row) for row in rows]

            params = {
                int(row.run_id): row.params
                for row in await conn.execute(text("SELECT run_id, params FROM run"))
            }
            counts: list[int] = []
            for table in ("order", "price_tick", "news", "market_event", "engine_state"):
                count = await conn.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE run_id = :r'), {"r": run_id}
                )
                counts.append(int(count.scalar_one()))
            config: dict[str, Any]
            (config,) = (
                await conn.execute(
                    text("SELECT config FROM run_config_revision WHERE run_id = :r"), {"r": run_id}
                )
            ).scalars()
            return (
                await drinks(source),
                await drinks(run_id),
                params[source],
                params[run_id],
                counts,
                config,
            )

    old, new, source_params, new_params, counts, config = _with_engine(settings, database_url, body)

    active = [row for row in old if row[-1]]
    assert [row[1] for row in new] == ["Bier", "Fris"]
    assert [row[0] for row in new] == [0, 1]
    # Every copied column, the product included, equals the source's; slot and id do not.
    assert [row[1:11] for row in new] == [row[1:11] for row in active]
    assert not {row[11] for row in new} & {row[11] for row in old}
    assert all(row[-1] for row in new)
    assert Params.from_dict(new_params) == Params.from_dict(source_params) == Params(step_quant=0.3)
    assert counts == [0, 0, 0, 0, 0]
    assert [d["name"] for d in config["drinks"]] == ["Bier", "Fris"]
    assert [d["drink_id"] for d in config["drinks"]] == [row[11] for row in new]


def test_create_run_from_an_unknown_source_is_run_not_found_creating_nothing(
    settings: Settings, database_url: str
) -> None:
    async def body(engine: AsyncEngine) -> int:
        with pytest.raises(RunNotFound):
            await create_run(engine, name="Nieuw", author="a", copy_from_run_id=999)
        async with engine.connect() as conn:
            return int((await conn.execute(text("SELECT count(*) FROM run"))).scalar_one())

    assert _with_engine(settings, database_url, body) == 0


# --- B-04 T5: a create with a profile (AC7-AC10, AC15; SD4, SD9; PD8, PD9) --------

WILD = dataclasses.replace(
    DEFAULT_PARAMS, eta=0.9, bm_sigma_y=0.5, y_clip=4.0, demand_enabled=True, idle_strength=3.0
)
WILD_SETTINGS = profile_settings(WILD, 30_000)
# A source run's params outside the 22, set apart from every default.
SOURCE = dataclasses.replace(
    Params(step_quant=0.3), bm_sigma=0.42, idle_targets=("Bier",), idle_rise_targets=("Fris",)
)


def _rest(params: Params) -> dict[str, Any]:
    """Every param a profile does not hold (SD4: these come from where they come today)."""
    return {
        field.name: getattr(params, field.name)
        for field in dataclasses.fields(params)
        if field.name not in PROFILE_FIELDS
    }


async def _profile(engine: AsyncEngine, values: dict[str, Any] = WILD_SETTINGS) -> int:
    async with engine.begin() as conn:
        row, _ = await save_profile(
            conn,
            name="Wilde beurs",
            settings=values,
            source_run_name="Proef",
            saved_by="a",
            overwrite=False,
        )
    return row.profile_id


async def _ended_source(engine: AsyncEngine, params: Params = SOURCE) -> int:
    async with engine.begin() as conn:
        source = await create_draft_run(conn, name="Vorige", params=params, run_seed=1)
        await _bier(conn, source, "Bier", slot=0)
        await _bier(conn, source, "Fris", slot=1)
    await _end(engine, source)
    return source


async def _created(
    engine: AsyncEngine, run_id: int
) -> tuple[Params, int, dict[str, Any], list[str]]:
    """The new run's params, Kaarsbreedte (ms), revision 1, and drink names."""
    async with engine.connect() as conn:
        run = (
            await conn.execute(
                text("SELECT params, candle_interval_ms FROM run WHERE run_id = :r"), {"r": run_id}
            )
        ).one()
        config: dict[str, Any]
        (config,) = (
            await conn.execute(
                text("SELECT config FROM run_config_revision WHERE run_id = :r"), {"r": run_id}
            )
        ).scalars()
        names: list[str] = list(
            (
                await conn.execute(
                    text("SELECT name FROM drink WHERE run_id = :r ORDER BY slot"), {"r": run_id}
                )
            ).scalars()
        )
        return Params.from_dict(run.params), int(run.candle_interval_ms), config, names


def test_a_create_with_a_profile_takes_its_22_and_the_latest_runs_rest(
    settings: Settings, database_url: str
) -> None:
    """AC7: Kaarsbreedte included; no drinks; revision 1 carries the profile's values."""

    async def body(engine: AsyncEngine) -> tuple[Params, int, dict[str, Any], list[str]]:
        await _ended_source(engine)
        profile_id = await _profile(engine)
        return await _created(
            engine, await create_run(engine, name="Nieuw", author="a", profile_id=profile_id)
        )

    params, candle, config, names = _with_engine(settings, database_url, body)

    assert profile_settings(params, candle) == WILD_SETTINGS
    assert candle == 30_000
    assert _rest(params) == _rest(SOURCE)
    assert names == []
    assert config["candle_interval_s"] == 30
    assert profile_settings(Params.from_dict(config["params"]), 30_000) == WILD_SETTINGS


def test_a_create_with_a_profile_on_an_empty_database_takes_the_defaults_rest(
    settings: Settings, database_url: str
) -> None:
    """AC7: else `DEFAULT_PARAMS` outside the 22."""

    async def body(engine: AsyncEngine) -> tuple[Params, int, dict[str, Any], list[str]]:
        profile_id = await _profile(engine)
        return await _created(
            engine, await create_run(engine, name="Nieuw", author="a", profile_id=profile_id)
        )

    params, candle, _, _ = _with_engine(settings, database_url, body)

    assert profile_settings(params, candle) == WILD_SETTINGS
    assert _rest(params) == _rest(DEFAULT_PARAMS)


def test_a_create_with_a_profile_and_a_copy_takes_the_copied_runs_drinks_and_rest(
    settings: Settings, database_url: str
) -> None:
    """AC8: the 22 from the profile; drinks, idle lists and `bm_sigma` from the copied run."""

    async def body(engine: AsyncEngine) -> tuple[Params, int, dict[str, Any], list[str]]:
        source = await _ended_source(engine)
        async with engine.begin() as conn:
            # The latest run, which a copy must not take from.
            await create_draft_run(
                conn, name="Nieuwer", params=Params(step_quant=0.9, bm_sigma=0.01), run_seed=1
            )
            await conn.execute(text("UPDATE run SET status = 'ended' WHERE name = 'Nieuwer'"))
        profile_id = await _profile(engine)
        run_id = await create_run(
            engine, name="Nieuw", author="a", copy_from_run_id=source, profile_id=profile_id
        )
        return await _created(engine, run_id)

    params, candle, config, names = _with_engine(settings, database_url, body)

    assert profile_settings(params, candle) == WILD_SETTINGS
    assert _rest(params) == _rest(SOURCE)
    assert names == ["Bier", "Fris"]
    assert [d["name"] for d in config["drinks"]] == ["Bier", "Fris"]


def test_a_create_with_a_copy_and_no_profile_is_unchanged(
    settings: Settings, database_url: str
) -> None:
    """AC9: the source's params exactly, Kaarsbreedte at its 60 s default."""

    async def body(engine: AsyncEngine) -> tuple[Params, int, dict[str, Any], list[str]]:
        async with engine.begin() as conn:
            source = await create_draft_run(conn, name="Vorige", params=SOURCE, run_seed=1)
            await conn.execute(
                text("UPDATE run SET candle_interval_ms = 30000 WHERE run_id = :r"), {"r": source}
            )
        await _end(engine, source)
        return await _created(
            engine, await create_run(engine, name="Nieuw", author="a", copy_from_run_id=source)
        )

    params, candle, config, _ = _with_engine(settings, database_url, body)

    assert params == SOURCE
    assert candle == 60_000
    assert config["candle_interval_s"] == 60


@pytest.mark.parametrize("fault", ["unknown", "out_of_range"])
def test_a_refused_profile_creates_no_run(
    settings: Settings, database_url: str, fault: str
) -> None:
    """AC10: 404 or 422, and nothing written."""

    async def body(engine: AsyncEngine) -> int:
        profile_id = await _profile(engine, WILD_SETTINGS | {"y_clip": 25})
        with pytest.raises(ProfileNotFound if fault == "unknown" else InvalidConfig):
            await create_run(
                engine,
                name="Nieuw",
                author="a",
                profile_id=999_999 if fault == "unknown" else profile_id,
            )
        async with engine.connect() as conn:
            return int((await conn.execute(text("SELECT count(*) FROM run"))).scalar_one())

    assert _with_engine(settings, database_url, body) == 0


def test_draft_exists_comes_before_the_profile_is_read(
    settings: Settings, database_url: str
) -> None:
    """PD8: today's refusals keep their precedence over an unknown profile."""

    async def body(engine: AsyncEngine) -> None:
        await create_run(engine, name="Concept", author="a")
        with pytest.raises(DraftExists):
            await create_run(engine, name="Nieuw", author="a", profile_id=999_999)

    _with_engine(settings, database_url, body)

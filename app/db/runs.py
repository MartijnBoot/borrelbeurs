"""Run and drink repositories.

Every function but `go_live` takes an `AsyncConnection` and never begins or
commits a transaction: the caller owns the transaction, so an import can
compose several of these into one atomic unit (SD15). `go_live` is itself one
whole transaction, so it takes the engine.

The only drink write besides `add_drink` is `set_bar_price`. Renaming and
removal are Phase 6.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import AppError
from app.db.engine_state import insert_state, insert_tick
from app.db.mapping import DrinkRow, params_to_json, spec_from_rows
from app.db.models import Drink, Run, RunConfigRevision
from exchange import EngineState, Params, initial_state

_NAME_INDEX = "drink_name_live"
_ONE_LIVE_INDEX = "run_one_live"


class DuplicateDrinkName(AppError):
    """A run already has a live drink whose name matches, trimmed and case-folded (SD14)."""

    status_code = 409
    code = "duplicate_drink_name"


class RunNotDraft(AppError):
    """Only a draft run can go live."""

    status_code = 409
    code = "run_not_draft"


class RunNotReady(AppError):
    """A draft run that cannot go live as configured: no drinks, or `auto_calibrate_s0` (PD14)."""

    status_code = 409
    code = "run_not_ready"


class LiveRunExists(AppError):
    """Another run is already live; at most one is (SD6, AC22)."""

    status_code = 409
    code = "live_run_exists"


def name_key(name: str) -> str:
    """The comparison form of a drink name (PD6), computed here, not by Postgres' `lower()`."""
    return name.strip().casefold()


async def create_draft_run(
    conn: AsyncConnection, *, name: str, params: Params, run_seed: int
) -> int:
    result = await conn.execute(
        insert(Run)
        .values(status="draft", name=name, params=params_to_json(params), run_seed=run_seed)
        .returning(Run.run_id)
    )
    return int(result.scalar_one())


async def add_drink(
    conn: AsyncConnection,
    run_id: int,
    *,
    name: str,
    slot: int,
    p_min_cents: int,
    p0_cents: int,
    p_max_cents: int,
    a: float,
    d: float,
    s0: float,
    c: float,
    bar_price_cents: int,
) -> int:
    """Insert one drink, or raise `DuplicateDrinkName` naming the clash."""
    statement = (
        insert(Drink)
        .values(
            run_id=run_id,
            slot=slot,
            name=name,
            name_key=name_key(name),
            p_min_cents=p_min_cents,
            p0_cents=p0_cents,
            p_max_cents=p_max_cents,
            a=a,
            d=d,
            s0=s0,
            c=c,
            bar_price_cents=bar_price_cents,
        )
        .returning(Drink.drink_id)
    )
    # A savepoint, so the violation leaves the caller's transaction usable.
    try:
        async with conn.begin_nested():
            result = await conn.execute(statement)
    except IntegrityError as error:
        if _NAME_INDEX not in str(error.orig):
            raise
        raise DuplicateDrinkName(
            f"run {run_id} already has a drink named {name!r} (names compare trimmed, "
            "ignoring case)"
        ) from error
    return int(result.scalar_one())


async def set_bar_price(conn: AsyncConnection, drink_id: int, cents: int) -> None:
    result = await conn.execute(
        update(Drink)
        .where(Drink.drink_id == drink_id)
        .values(bar_price_cents=cents)
        .returning(Drink.drink_id)
    )
    if result.scalar_one_or_none() is None:
        raise LookupError(f"no drink {drink_id}")


async def append_config_revision(
    conn: AsyncConnection, run_id: int, *, config: dict[str, Any], author: str
) -> int:
    """Record `config` as the run's next revision, numbered from 1, and return its number."""
    latest = (
        select(func.coalesce(func.max(RunConfigRevision.revision), 0) + 1)
        .where(RunConfigRevision.run_id == run_id)
        .scalar_subquery()
    )
    result = await conn.execute(
        insert(RunConfigRevision)
        .values(run_id=run_id, revision=latest, config=config, author=author)
        .returning(RunConfigRevision.revision)
    )
    return int(result.scalar_one())


async def all_drinks(conn: AsyncConnection, run_id: int) -> list[DrinkRow]:
    """Every drink of the run, removed ones included, in slot order (SD15)."""
    result = await conn.execute(
        select(
            Drink.drink_id,
            Drink.slot,
            Drink.name,
            Drink.p_min_cents,
            Drink.p0_cents,
            Drink.p_max_cents,
            Drink.a,
            Drink.d,
            Drink.s0,
            Drink.c,
            Drink.bar_price_cents,
            Drink.removed_at.is_not(None).label("removed"),
        )
        .where(Drink.run_id == run_id)
        .order_by(Drink.slot)
    )
    return [DrinkRow(**row._asdict()) for row in result]


async def active_drinks(conn: AsyncConnection, run_id: int) -> list[DrinkRow]:
    """The run's drinks that are not removed, in slot order."""
    return [row for row in await all_drinks(conn, run_id) if not row.removed]


async def go_live(engine: AsyncEngine, run_id: int, *, now_ms: int) -> EngineState:
    """Move a draft run to live with its initial state and `reset` tick, in one transaction."""
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                select(Run.status, Run.params).where(Run.run_id == run_id).with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise LookupError(f"no run {run_id}")
        if row.status != "draft":
            raise RunNotDraft(f"run {run_id} is {row.status}, not draft")
        drinks = await active_drinks(conn, run_id)
        if not drinks:
            raise RunNotReady(f"run {run_id} has no drinks")
        params = Params.from_dict(row.params)
        if params.auto_calibrate_s0:
            # `initial_state` leaves calibration to the caller, and calibrating
            # here would rewrite `drink.s0` -- an admin edit (Phase 6).
            raise RunNotReady(f"run {run_id} has auto_calibrate_s0 set, which go-live rejects")
        spec, drink_ids = spec_from_rows(drinks, params)

        try:
            async with conn.begin_nested():
                await conn.execute(
                    update(Run)
                    .where(Run.run_id == run_id)
                    .values(status="live", started_at=func.now())
                )
        except IntegrityError as error:
            if _ONE_LIVE_INDEX not in str(error.orig):
                raise
            raise LiveRunExists(f"another run is already live; run {run_id} stays draft") from error

        state = initial_state(spec, now_ms=now_ms)
        await insert_state(conn, run_id=run_id, state=state, drink_ids=drink_ids, wall_ts_ms=now_ms)
        await insert_tick(
            conn,
            run_id=run_id,
            state=state,
            spec=spec,
            drink_ids=drink_ids,
            source="reset",
            wall_ts_ms=now_ms,
        )
    return state

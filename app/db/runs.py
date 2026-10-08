"""Run and drink repositories.

Every function but `create_run` and `go_live` takes an `AsyncConnection` and
never begins or commits a transaction: the caller owns the transaction, so an
import can compose several of these into one atomic unit (SD15). `create_run`
and `go_live` are each one whole transaction, so they take the engine.

**At most one draft (Phase 6 SD2).** No index enforces it: `import_v1` makes a
draft per import. `create_run` serialises itself instead (the user's choice,
2026-10-06): its transaction first takes `run` in SHARE ROW EXCLUSIVE mode,
which conflicts with itself, so two creates cannot both see "no draft".

The only drink write besides `add_drink` is `set_bar_price`. Renaming and
removal are Phase 6.

**Revision numbers** are allocated under a row lock on `run` (Phase 6 SD6), so
concurrent writers of one run get consecutive revisions, never the same `max + 1`.
"""

from __future__ import annotations

import dataclasses
import secrets
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import AppError
from app.db.engine_state import insert_state, insert_tick
from app.db.mapping import DrinkRow, params_to_json, spec_from_rows
from app.db.models import Drink, Run, RunConfigRevision
from exchange import EngineState, Params, anchor_s0_to_current_y, initial_state

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


class RunNotFound(AppError):
    """No run has this id (Phase 6 PD4)."""

    status_code = 404
    code = "run_not_found"


class RunNotReady(AppError):
    """A draft run that cannot go live as configured: it has no drinks."""

    status_code = 409
    code = "run_not_ready"


class LiveRunExists(AppError):
    """Another run is already live; at most one is (SD6, AC22)."""

    status_code = 409
    code = "live_run_exists"


class RunEnded(AppError):
    """An ended run's config is history; no route reads or writes it (Phase 6 SD5)."""

    status_code = 409
    code = "run_ended"


class DraftExists(AppError):
    """A draft already exists (Phase 6 SD2); the error carries its `run_id` (PD2)."""

    status_code = 409
    code = "draft_exists"


RunStatus = Literal["draft", "live", "ended"]


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    name: str
    status: RunStatus


@dataclass(frozen=True)
class RunRow:
    """The `run` columns a config read or write needs."""

    run_id: int
    name: str
    status: RunStatus
    params: dict[str, Any]
    candle_interval_ms: int


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
    """Record `config` as the run's next revision, numbered from 1, and return its number.

    Takes the `run` row lock first (SD6); a caller that already holds it loses nothing.
    """
    await conn.execute(select(Run.run_id).where(Run.run_id == run_id).with_for_update())
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


async def latest_revision(conn: AsyncConnection, run_id: int) -> int:
    """The run's newest revision number, 0 if it has none."""
    result = await conn.execute(
        select(func.coalesce(func.max(RunConfigRevision.revision), 0)).where(
            RunConfigRevision.run_id == run_id
        )
    )
    return int(result.scalar_one())


async def get_run(conn: AsyncConnection, run_id: int, *, lock: bool = False) -> RunRow:
    """The run, or `RunNotFound`; with `lock`, under `SELECT … FOR UPDATE` (SD6)."""
    statement = select(Run.run_id, Run.name, Run.status, Run.params, Run.candle_interval_ms).where(
        Run.run_id == run_id
    )
    row = (await conn.execute(statement.with_for_update() if lock else statement)).one_or_none()
    if row is None:
        raise RunNotFound(f"no run {run_id}")
    return RunRow(
        int(row.run_id), row.name, row.status, dict(row.params), int(row.candle_interval_ms)
    )


async def update_run(
    conn: AsyncConnection,
    run_id: int,
    *,
    name: str,
    params: dict[str, Any],
    candle_interval_ms: int,
) -> None:
    await conn.execute(
        update(Run)
        .where(Run.run_id == run_id)
        .values(name=name, params=params, candle_interval_ms=candle_interval_ms)
    )


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


async def current_run(conn: AsyncConnection) -> RunSummary | None:
    """The live run, else the newest draft, else `None` (Phase 6 SD4, PD2)."""
    row = (
        await conn.execute(
            select(Run.run_id, Run.name, Run.status)
            .where(Run.status.in_(("live", "draft")))
            .order_by((Run.status == "live").desc(), Run.created_at.desc(), Run.run_id.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else RunSummary(int(row.run_id), row.name, row.status)


async def latest_params(conn: AsyncConnection) -> Params | None:
    """The params of the most recently created run, if any (Phase 6 SD2)."""
    params = (
        await conn.execute(
            select(Run.params).order_by(Run.created_at.desc(), Run.run_id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return None if params is None else Params.from_dict(params)


async def create_run(engine: AsyncEngine, *, name: str, author: str) -> int:
    """A new draft and its revision 1, or `LiveRunExists` / `DraftExists` (Phase 6 SD2, PD6)."""
    name = name.strip()
    async with engine.begin() as conn:
        # Conflicts with itself, so a concurrent create waits here until this commits.
        await conn.execute(text("LOCK TABLE run IN SHARE ROW EXCLUSIVE MODE"))
        current = await current_run(conn)
        if current is not None and current.status == "live":
            raise LiveRunExists(f"run {current.run_id} is live; end it before creating another")
        if current is not None:
            raise DraftExists(
                f"run {current.run_id} is already a draft", extra={"run_id": current.run_id}
            )
        params = await latest_params(conn) or Params()
        run_id = await create_draft_run(
            conn, name=name, params=params, run_seed=secrets.randbits(63)
        )
        await append_config_revision(
            conn,
            run_id,
            config={"name": name, "params": params_to_json(params), "drinks": []},
            author=author,
        )
    return run_id


async def go_live(
    engine: AsyncEngine, run_id: int, *, now_ms: int, author: str = "cli"
) -> EngineState:
    """Move a draft run to live with its initial state and `reset` tick, in one transaction.

    With `auto_calibrate_s0`, the same transaction anchors `s0` on the initial
    prices (`anchor_s0_to_current_y`), writes each `drink.s0`, and appends one
    config revision by `author` (Phase 6 SD3). `author` is the API key's label,
    or `"cli"` from `app.cli.runs`.
    """
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                select(Run.status, Run.name, Run.params)
                .where(Run.run_id == run_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise RunNotFound(f"no run {run_id}")
        if row.status != "draft":
            raise RunNotDraft(f"run {run_id} is {row.status}, not draft")
        drinks = await active_drinks(conn, run_id)
        if not drinks:
            raise RunNotReady(f"run {run_id} has no drinks")
        params = Params.from_dict(row.params)
        spec, drink_ids = spec_from_rows(drinks, params)
        state = initial_state(spec, now_ms=now_ms)
        if params.auto_calibrate_s0:
            spec = anchor_s0_to_current_y(spec, state.y)
            for drink_id, s0 in zip(drink_ids, spec.s0.tolist(), strict=True):
                await conn.execute(update(Drink).where(Drink.drink_id == drink_id).values(s0=s0))
            await append_config_revision(
                conn,
                run_id,
                config={
                    "name": row.name,
                    "params": params_to_json(params),
                    "drinks": [
                        {**dataclasses.asdict(d), "s0": s0}
                        for d, s0 in zip(drinks, spec.s0.tolist(), strict=True)
                    ],
                },
                author=author,
            )

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

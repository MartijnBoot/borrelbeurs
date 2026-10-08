"""Drinks of a run: add, edit and remove (Phase 6 SD5, SD9, SD11-SD13, SD16, SD17).

**Validation (SD8, per drink).** `DrinkCreate` forbids unknown keys and any
explicit `null`. Money is strict integer cents: `p_min_cents ≥ 0`,
`bar_price_cents ≥ 0`, and `p_min < p0 < p_max` on the resulting row: 422
naming the bound fields the request gave (`p0_cents` for an add). `a/d/s0/c`
are strict and finite. The name is 1-40 characters after trim. An absent
optional field of an add takes the server default:
`bar_price_cents = p0_cents`, `a = 10`, `d = 0.6`, `s0 = 8`, `c = 0.4` (AC4).

**The slot** is `max(slot) + 1` over every row of the run, removed ones
included, so a re-added name gets a new `drink_id` and slot (AC21). A name that
matches an active drink, trimmed and case-folded, is 409 `duplicate_drink_name`
(`add_drink`'s mapping).

**A draft add** is the insert and a revision in one transaction. **A live add
(SD12)** is one `mutate("config")`: the spec is rebuilt from every row, the
state is `append_slot` -- the new drink starts as `initial_state` starts one,
every existing slot unchanged -- and `commit_transition` writes the rest.

**An edit** (`DrinkPatch`) changes only the fields present, validated on the
resulting row; one that changes nothing writes nothing (AC2). A removed drink
is 409 `drink_removed`. A rename rewrites the name in both idle-target lists of
`run.params`, in the same transaction (SD11). On the live run it is one
`mutate("config")`: a `p_min`/`p_max` change holds that slot's quoted price
(`hold_quoted_prices`, its jump cancelled); any other change moves no `y` (SD9).

**A removal (SD13)** drops the drink from both idle-target lists. On a draft it
deletes the row: there is no ledger to keep. On the live run it is one
`mutate("config")`: `removed_at` is set, the spec is rebuilt with that slot
masked, and every jump on the slot -- a market event's included -- is cancelled,
because `apply_jumps` does not read the mask (PD17). Its orders and revenue stay.
Removing the last active drink is 409 `last_active_drink` (SD16).
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.mapping import DrinkRow, spec_from_rows
from app.db.runs import (
    DrinkNotFound,
    DrinkRemoved,
    LastActiveDrink,
    RunNotDraft,
    RunRow,
    add_drink,
    all_drinks,
    delete_drink,
    get_run,
    latest_revision,
    next_slot,
    remove_drink,
    update_drink,
    update_run,
)
from app.runtime.clock import Clock
from app.runtime.config import (
    InvalidConfig,
    append_revision,
    commit_transition,
    current_revision,
    readable,
)
from app.runtime.holder import MarketHolder, MarketView, Outcome
from exchange import Params, append_slot, cancel_jumps, hold_quoted_prices

DEFAULT_A = 10.0
DEFAULT_D = 0.6
DEFAULT_S0 = 8.0
DEFAULT_C = 0.4

DrinkName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Cents = Annotated[int, Field(strict=True, ge=0)]
Coefficient = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def _not_null(value: Any) -> Any:
    if value is None:
        raise ValueError("may not be null")
    return value


class DrinkCreate(BaseModel):
    """`POST /api/runs/{run_id}/drinks` (SD5). An optional field is absent or a value."""

    model_config = ConfigDict(extra="forbid")

    name: DrinkName
    p_min_cents: Cents
    p0_cents: StrictInt
    p_max_cents: StrictInt
    bar_price_cents: Cents | None = None
    a: Coefficient | None = None
    d: Coefficient | None = None
    s0: Coefficient | None = None
    c: Coefficient | None = None

    _no_null = field_validator("*", mode="before")(_not_null)


class DrinkPatch(BaseModel):
    """`PATCH /api/runs/{run_id}/drinks/{drink_id}` (SD5): any subset, `PATCH config`'s rules."""

    model_config = ConfigDict(extra="forbid")

    name: DrinkName | None = None
    p_min_cents: Cents | None = None
    p0_cents: StrictInt | None = None
    p_max_cents: StrictInt | None = None
    bar_price_cents: Cents | None = None
    a: Coefficient | None = None
    d: Coefficient | None = None
    s0: Coefficient | None = None
    c: Coefficient | None = None

    _no_null = field_validator("*", mode="before")(_not_null)


class CreatedDrink(BaseModel):
    drink_id: int
    revision: int


_BOUNDS = ("p_min_cents", "p0_cents", "p_max_cents")


def check_bounds(
    p_min_cents: int, p0_cents: int, p_max_cents: int, *, named: tuple[str, ...] = ("p0_cents",)
) -> None:
    """`p_min < p0 < p_max` on the resulting row, or 422 naming each of `named` (SD8, AC11)."""
    if not p_min_cents < p0_cents < p_max_cents:
        raise InvalidConfig(
            f"p0_cents {p0_cents} must lie strictly between p_min_cents {p_min_cents} "
            f"and p_max_cents {p_max_cents}",
            extra={
                "faults": [
                    {"loc": ["body", field], "msg": "p_min_cents < p0_cents < p_max_cents"}
                    for field in named
                ]
            },
        )


def _bar_price(body: DrinkCreate) -> int:
    return body.p0_cents if body.bar_price_cents is None else body.bar_price_cents


async def _insert(conn: AsyncConnection, run_id: int, body: DrinkCreate) -> int:
    return await add_drink(
        conn,
        run_id,
        name=body.name,
        slot=await next_slot(conn, run_id),
        p_min_cents=body.p_min_cents,
        p0_cents=body.p0_cents,
        p_max_cents=body.p_max_cents,
        a=DEFAULT_A if body.a is None else body.a,
        d=DEFAULT_D if body.d is None else body.d,
        s0=DEFAULT_S0 if body.s0 is None else body.s0,
        c=DEFAULT_C if body.c is None else body.c,
        bar_price_cents=_bar_price(body),
    )


async def add_draft_drink(
    engine: AsyncEngine, run_id: int, body: DrinkCreate, *, author: str
) -> CreatedDrink:
    """Add a drink to a draft run, with its revision."""
    check_bounds(body.p_min_cents, body.p0_cents, body.p_max_cents)
    async with engine.begin() as conn:
        run = readable(await get_run(conn, run_id, lock=True))
        if run.status != "draft":
            raise RunNotDraft(f"run {run_id} is {run.status}, and not live in this process")
        drink_id = await _insert(conn, run_id, body)
        return CreatedDrink(
            drink_id=drink_id, revision=await append_revision(conn, run, author=author)
        )


async def add_live_drink(
    holder: MarketHolder, run_id: int, body: DrinkCreate, *, author: str, clock: Clock
) -> CreatedDrink:
    """Add a drink to the live run as one engine transition (SD7, SD12)."""
    check_bounds(body.p_min_cents, body.p0_cents, body.p_max_cents)
    engine = holder.engine

    async def step(view: MarketView) -> Outcome[CreatedDrink]:
        assert view.run_id == run_id and view.spec is not None and view.state is not None
        now_ms = clock.wall_ms()
        async with engine.begin() as conn:
            run = readable(await get_run(conn, run_id, lock=True))
            drink_id = await _insert(conn, run_id, body)
            spec, drink_ids = spec_from_rows(await all_drinks(conn, run_id), view.spec.params)
            assert drink_ids == (*view.drink_ids, drink_id)
            revision = await append_revision(conn, run, author=author)
            outcome = await commit_transition(
                conn,
                view,
                run,
                spec=spec,
                state=append_slot(spec, view.state, now_ms=now_ms),
                revision=revision,
                now_ms=now_ms,
                drink_ids=drink_ids,
                bar_price_cents={**view.bar_price_cents, drink_id: _bar_price(body)},
            )
        return Outcome(
            result=CreatedDrink(drink_id=drink_id, revision=revision),
            view=outcome.view,
            events=outcome.events,
            ticks=outcome.ticks,
            ring_window_ms=outcome.ring_window_ms,
        )

    return await holder.mutate("config", step)


def _edited(row: DrinkRow, patch: DrinkPatch) -> DrinkRow | None:
    """`row` with the present fields of `patch`, checked; `None` if that changes nothing."""
    edited = dataclasses.replace(row, **patch.model_dump(exclude_unset=True))
    named = tuple(f for f in _BOUNDS if f in patch.model_fields_set)
    check_bounds(edited.p_min_cents, edited.p0_cents, edited.p_max_cents, named=named)
    return None if edited == row else edited


def _renamed(params: dict[str, Any], old: str, new: str | None) -> dict[str, Any]:
    """`run.params` with `old` replaced by `new` in both idle-target lists, or dropped (SD11)."""
    return {
        **params,
        **{
            field: [
                new if name == old else name
                for name in params.get(field, [])
                if name != old or new is not None
            ]
            for field in ("idle_targets", "idle_rise_targets")
        },
    }


def _active_row(drinks: list[DrinkRow], run_id: int, drink_id: int) -> DrinkRow:
    """The drink, or 404 `drink_not_found` / 409 `drink_removed`."""
    row = next((d for d in drinks if d.drink_id == drink_id), None)
    if row is None:
        raise DrinkNotFound(f"run {run_id} has no drink {drink_id}")
    if row.removed:
        raise DrinkRemoved(f"drink {drink_id} was removed from run {run_id}")
    return row


async def _write_params(conn: AsyncConnection, run: RunRow) -> None:
    await update_run(
        conn,
        run.run_id,
        name=run.name,
        params=run.params,
        candle_interval_ms=run.candle_interval_ms,
    )


async def _edit(
    conn: AsyncConnection, run: RunRow, drink_id: int, patch: DrinkPatch, *, author: str
) -> tuple[RunRow, list[DrinkRow], DrinkRow, int] | None:
    """Write the edit and its revision, under the caller's `run` row lock.

    The run as it now is, every drink row as it now is, the drink before the
    edit, and the revision; `None` if the edit changes nothing.
    """
    drinks = await all_drinks(conn, run.run_id)
    row = _active_row(drinks, run.run_id, drink_id)
    edited = _edited(row, patch)
    if edited is None:
        return None
    await update_drink(conn, run.run_id, edited)
    if edited.name != row.name:
        run = dataclasses.replace(run, params=_renamed(run.params, row.name, edited.name))
        await _write_params(conn, run)
    drinks = [edited if d.drink_id == drink_id else d for d in drinks]
    return run, drinks, row, await append_revision(conn, run, author=author)


async def edit_draft_drink(
    engine: AsyncEngine, run_id: int, drink_id: int, patch: DrinkPatch, *, author: str
) -> int:
    """Edit a draft run's drink; the new revision, or the current one if nothing changed."""
    if not patch.model_fields_set:
        return await current_revision(engine, run_id)
    async with engine.begin() as conn:
        run = readable(await get_run(conn, run_id, lock=True))
        if run.status != "draft":
            raise RunNotDraft(f"run {run_id} is {run.status}, and not live in this process")
        written = await _edit(conn, run, drink_id, patch, author=author)
        return await latest_revision(conn, run_id) if written is None else written[3]


async def edit_live_drink(
    holder: MarketHolder,
    run_id: int,
    drink_id: int,
    patch: DrinkPatch,
    *,
    author: str,
    clock: Clock,
) -> int:
    """Edit a drink of the live run as one engine transition (SD7, SD9); the new revision."""
    engine = holder.engine
    if not patch.model_fields_set:
        return await current_revision(engine, run_id)

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id == run_id and view.spec is not None and view.state is not None
        now_ms = clock.wall_ms()
        async with engine.begin() as conn:
            run = readable(await get_run(conn, run_id, lock=True))
            written = await _edit(conn, run, drink_id, patch, author=author)
            if written is None:
                return Outcome(result=await latest_revision(conn, run_id), view=view)
            run, drinks, before, revision = written
            spec, drink_ids = spec_from_rows(drinks, Params.from_dict(run.params))
            assert drink_ids == view.drink_ids
            state = view.state
            after = next(d for d in drinks if d.drink_id == drink_id)
            if (after.p_min_cents, after.p_max_cents) != (before.p_min_cents, before.p_max_cents):
                state = hold_quoted_prices(view.spec, spec, state, [drink_ids.index(drink_id)])
            return await commit_transition(
                conn,
                view,
                run,
                spec=spec,
                state=state,
                revision=revision,
                now_ms=now_ms,
                bar_price_cents={**view.bar_price_cents, drink_id: after.bar_price_cents},
            )

    return await holder.mutate("config", step)


async def _remove(
    conn: AsyncConnection, run: RunRow, drink_id: int, *, author: str
) -> tuple[RunRow, list[DrinkRow], int]:
    """Remove the drink and append the revision, under the caller's `run` row lock.

    A draft's row is deleted, a live run's masked. The run and every drink row as
    they now are, and the revision.
    """
    drinks = await all_drinks(conn, run.run_id)
    row = _active_row(drinks, run.run_id, drink_id)
    if not any(not d.removed and d.drink_id != drink_id for d in drinks):
        raise LastActiveDrink(f"drink {drink_id} is the last active drink of run {run.run_id}")
    if run.status == "draft":
        await delete_drink(conn, drink_id)
        drinks = [d for d in drinks if d.drink_id != drink_id]
    else:
        await remove_drink(conn, drink_id)
        drinks = [dataclasses.replace(d, removed=True) if d is row else d for d in drinks]
    run = dataclasses.replace(run, params=_renamed(run.params, row.name, None))
    await _write_params(conn, run)
    return run, drinks, await append_revision(conn, run, author=author)


async def remove_draft_drink(
    engine: AsyncEngine, run_id: int, drink_id: int, *, author: str
) -> int:
    """Delete a draft run's drink; the new revision."""
    async with engine.begin() as conn:
        run = readable(await get_run(conn, run_id, lock=True))
        if run.status != "draft":
            raise RunNotDraft(f"run {run_id} is {run.status}, and not live in this process")
        _, _, revision = await _remove(conn, run, drink_id, author=author)
        return revision


async def remove_live_drink(
    holder: MarketHolder, run_id: int, drink_id: int, *, author: str, clock: Clock
) -> int:
    """Remove a drink from the live run as one engine transition (SD7, SD13); the new revision."""
    engine = holder.engine

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id == run_id and view.spec is not None and view.state is not None
        now_ms = clock.wall_ms()
        async with engine.begin() as conn:
            run = readable(await get_run(conn, run_id, lock=True))
            run, drinks, revision = await _remove(conn, run, drink_id, author=author)
            spec, drink_ids = spec_from_rows(drinks, Params.from_dict(run.params))
            assert drink_ids == view.drink_ids
            return await commit_transition(
                conn,
                view,
                run,
                spec=spec,
                state=cancel_jumps(view.state, [drink_ids.index(drink_id)]),
                revision=revision,
                now_ms=now_ms,
            )

    return await holder.mutate("config", step)

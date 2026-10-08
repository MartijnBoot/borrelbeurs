"""Drinks of a run: add (Phase 6 SD5, SD12, SD17).

**Validation (SD8, per drink).** `DrinkCreate` forbids unknown keys and any
explicit `null`. Money is strict integer cents: `p_min_cents ≥ 0`,
`bar_price_cents ≥ 0`, and `p_min < p0 < p_max` on the resulting row, which is
422 naming `p0_cents`. `a/d/s0/c` are strict and finite. The name is 1-40
characters after trim. An absent optional field takes the server default:
`bar_price_cents = p0_cents`, `a = 10`, `d = 0.6`, `s0 = 8`, `c = 0.4` (AC4).

**The slot** is `max(slot) + 1` over every row of the run, removed ones
included, so a re-added name gets a new `drink_id` and slot (AC21). A name that
matches an active drink, trimmed and case-folded, is 409 `duplicate_drink_name`
(`add_drink`'s mapping).

**A draft add** is the insert and a revision in one transaction. **A live add
(SD12)** is one `mutate("config")`: the spec is rebuilt from every row, the
state is `append_slot` -- the new drink starts as `initial_state` starts one,
every existing slot unchanged -- and `commit_transition` writes the rest.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.mapping import spec_from_rows
from app.db.runs import RunNotDraft, add_drink, all_drinks, get_run, next_slot
from app.runtime.clock import Clock
from app.runtime.config import (
    InvalidConfig,
    append_revision,
    commit_transition,
    readable,
)
from app.runtime.holder import MarketHolder, MarketView, Outcome
from exchange import append_slot

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


class CreatedDrink(BaseModel):
    drink_id: int
    revision: int


def check_bounds(p_min_cents: int, p0_cents: int, p_max_cents: int) -> None:
    """`p_min < p0 < p_max` on the resulting row, or 422 naming `p0_cents` (SD8, AC11)."""
    if not p_min_cents < p0_cents < p_max_cents:
        raise InvalidConfig(
            f"p0_cents {p0_cents} must lie strictly between p_min_cents {p_min_cents} "
            f"and p_max_cents {p_max_cents}",
            extra={
                "faults": [
                    {
                        "loc": ["body", "p0_cents"],
                        "msg": "must lie strictly between p_min_cents and p_max_cents",
                    }
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

"""A run's config: the SD8 PATCH model, the config document, and draft writes.

**Validation (Phase 6 SD8)** is `ConfigPatch` and `ParamsPatch`, defined in
`app/runtime/config_patch.py` (a leaf, so `app/db` can use the same rules for a
profile, B-04) and re-exported here.

**The document (PD6).** `config_document` is the `GET` body: the newest
revision, the run, SD8's params, and every drink in slot order, removed ones
included with `active: false`. It is also what a revision stores, numbered as
that revision.

**Idle targets (SD11, PD7).** `run.params` keeps v1's name lists, so the engine
is unchanged; the wire carries `drink_id`s. The document maps stored names over
the active drinks and drops a name with none. A write takes `drink_id`s, and one
that is unknown or removed is 422 naming the field.

**A draft write (SD5, SD6)** is one plain transaction: lock the `run` row,
merge only the present keys, and append a revision only if something changed.
**A live write (SD7)** does the same inside `holder.mutate("config", ...)`, and
in that one transaction also compare-and-sets `engine_state` to `version + 1`
and writes a `price_tick` of source `config`; it emits `ConfigChanged`. An
empty body returns the current revision and writes nothing (AC2). An ended run
is 409 `run_ended`.

**Anchor s0 (SD5, SD26)** is v1's "📌 Zet huidige prijs als evenwicht", live
only: one `mutate("config")` running `anchor_s0_to_current_y` on the masked
spec -- the mean over active drinks, a removed drink's `s0` kept (AC16) -- and
writing every active drink's `drink.s0`. No `y` moves. A draft is 409
`run_not_live`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.codec import tick_prices
from app.db.engine_state import compare_and_set, insert_tick
from app.db.mapping import DrinkRow
from app.db.runs import (
    RunEnded,
    RunNotDraft,
    RunNotLive,
    RunRow,
    RunStatus,
    all_drinks,
    append_config_revision,
    get_run,
    latest_revision,
    set_drink_s0,
    update_run,
)
from app.runtime.clock import Clock, commit_stamp_ms
from app.runtime.config_patch import ConfigPatch as ConfigPatch
from app.runtime.config_patch import InvalidConfig as InvalidConfig
from app.runtime.config_patch import ParamsPatch as ParamsPatch
from app.runtime.config_patch import _whole_cents as _whole_cents
from app.runtime.history import TickEntry
from app.runtime.holder import ConfigChanged, MarketHolder, MarketView, Outcome
from exchange import EngineState, MarketSpec, Params, anchor_s0_to_current_y, hold_quoted_prices


class ParamsData(BaseModel):
    step_quant: float
    eta: float
    K: float
    lambda_orders: float
    alpha_price: float
    phi_persist: float
    decay_rho: float
    history_window_minutes: float
    refresh_minutes: float
    idle_decay_minutes: float
    idle_rise_minutes: float
    idle_strength: float
    idle_rise_strength: float
    idle_targets: list[int]
    idle_rise_targets: list[int]
    demand_enabled: bool
    auto_calibrate_s0: bool
    bm_enabled: bool
    bm_sigma_y: float
    bm_dt_minutes: float
    flow_vol_amp: float
    flow_beta: float
    y_clip: float


class RunConfigData(BaseModel):
    run_id: int
    name: str
    status: RunStatus
    candle_interval_s: int


class DrinkConfigData(BaseModel):
    drink_id: int
    slot: int
    name: str
    active: bool
    p_min_cents: int
    p0_cents: int
    p_max_cents: int
    bar_price_cents: int
    a: float
    d: float
    s0: float
    c: float


class ConfigData(BaseModel):
    """`GET /api/runs/{run_id}/config`, and what a revision stores (PD6)."""

    revision: int
    run: RunConfigData
    params: ParamsData
    drinks: list[DrinkConfigData]


class RevisionData(BaseModel):
    revision: int


_TARGETS = ("idle_targets", "idle_rise_targets")


def readable(run: RunRow) -> RunRow:
    """`run`, unless it has ended (`RunEnded`, SD5)."""
    if run.status == "ended":
        raise RunEnded(f"run {run.run_id} has ended")
    return run


async def config_document(conn: AsyncConnection, run: RunRow) -> ConfigData:
    """The run's config as `GET` returns it, numbered as its newest revision."""
    drinks = await all_drinks(conn, run.run_id)
    active = {d.name: d.drink_id for d in drinks if not d.removed}
    params = Params.from_dict(run.params)
    scalars = {
        name: getattr(params, name) for name in ParamsData.model_fields if name not in _TARGETS
    }
    targets = {name: [active[n] for n in getattr(params, name) if n in active] for name in _TARGETS}
    return ConfigData(
        revision=await latest_revision(conn, run.run_id),
        run=RunConfigData(
            run_id=run.run_id,
            name=run.name,
            status=run.status,
            candle_interval_s=run.candle_interval_ms // 1000,
        ),
        params=ParamsData.model_validate({**scalars, **targets}),
        drinks=[_drink_data(d) for d in drinks],
    )


def _drink_data(row: DrinkRow) -> DrinkConfigData:
    return DrinkConfigData(
        drink_id=row.drink_id,
        slot=row.slot,
        name=row.name,
        active=not row.removed,
        p_min_cents=row.p_min_cents,
        p0_cents=row.p0_cents,
        p_max_cents=row.p_max_cents,
        bar_price_cents=row.bar_price_cents,
        a=row.a,
        d=row.d,
        s0=row.s0,
        c=row.c,
    )


async def read_config(engine: AsyncEngine, run_id: int) -> ConfigData:
    async with engine.connect() as conn:
        return await config_document(conn, readable(await get_run(conn, run_id)))


def _target_names(drinks: list[DrinkRow], field: str, drink_ids: list[int]) -> list[str]:
    """`drink_ids` as names, in slot order, or 422 naming `field` (PD7)."""
    wanted = set(drink_ids)
    active = [d for d in drinks if not d.removed]
    unknown = wanted - {d.drink_id for d in active}
    if unknown:
        raise InvalidConfig(
            f"{field}: {sorted(unknown)} is not an active drink of this run",
            extra={
                "faults": [
                    {"loc": ["body", "params", field], "msg": "not an active drink of this run"}
                ]
            },
        )
    return [d.name for d in active if d.drink_id in wanted]


def _is_empty(patch: ConfigPatch) -> bool:
    return (
        patch.name is None
        and patch.candle_interval_s is None
        and (patch.params is None or not patch.params.model_fields_set)
    )


async def _merged(conn: AsyncConnection, run: RunRow, patch: ConfigPatch) -> RunRow | None:
    """`run` with only the present keys of `patch` applied; `None` if that changes nothing."""
    changes: dict[str, Any] = patch.params.model_dump(exclude_unset=True) if patch.params else {}
    drinks = await all_drinks(conn, run.run_id)
    for field in _TARGETS:
        if field in changes:
            changes[field] = _target_names(drinks, field, changes[field])
    merged = dataclasses.replace(
        run,
        name=run.name if patch.name is None else patch.name,
        candle_interval_ms=(
            run.candle_interval_ms
            if patch.candle_interval_s is None
            else patch.candle_interval_s * 1000
        ),
        params={**run.params, **changes},
    )
    return None if merged == run else merged


async def _record(conn: AsyncConnection, run: RunRow, *, author: str) -> int:
    """Write `run`'s columns and append its config as the next revision; that revision."""
    await update_run(
        conn,
        run.run_id,
        name=run.name,
        params=run.params,
        candle_interval_ms=run.candle_interval_ms,
    )
    return await append_revision(conn, run, author=author)


async def append_revision(conn: AsyncConnection, run: RunRow, *, author: str) -> int:
    """Append the run's config as it now stands as the next revision (PD6); that revision.

    The caller holds the `run` row lock (SD6).
    """
    document = await config_document(conn, run)
    document.revision += 1  # the number this append takes: the row lock is held
    revision = await append_config_revision(
        conn, run.run_id, config=document.model_dump(mode="json"), author=author
    )
    assert revision == document.revision
    return revision


async def commit_transition(
    conn: AsyncConnection,
    view: MarketView,
    run: RunRow,
    *,
    spec: MarketSpec,
    state: EngineState,
    revision: int,
    now_ms: int,
    drink_ids: tuple[int, ...] | None = None,
    bar_price_cents: Mapping[int, int] | None = None,
) -> Outcome[int]:
    """A live config transition's engine half (SD7), inside the caller's transaction.

    `state` becomes `version + 1` by compare-and-set, with a `price_tick` of
    source `config`. The outcome carries the new view, one `ConfigChanged` and
    the tick; and the ring's new window if `history_window_minutes` changed (PD18).
    `drink_ids` and `bar_price_cents` default to the view's: only an add changes them.
    """
    assert view.spec is not None and view.state is not None
    drink_ids = view.drink_ids if drink_ids is None else drink_ids
    candidate = dataclasses.replace(state, version=view.state.version + 1)
    await compare_and_set(
        conn,
        run_id=run.run_id,
        expected_version=view.state.version,
        state=candidate,
        drink_ids=drink_ids,
        wall_ts_ms=now_ms,
    )
    await insert_tick(
        conn,
        run_id=run.run_id,
        state=candidate,
        spec=spec,
        drink_ids=drink_ids,
        source="config",
        wall_ts_ms=now_ms,
    )
    window = spec.params.history_window_minutes
    return Outcome(
        result=revision,
        view=dataclasses.replace(
            view,
            spec=spec,
            state=candidate,
            drink_ids=drink_ids,
            bar_price_cents=view.bar_price_cents if bar_price_cents is None else bar_price_cents,
            last_commit_wall_ms=now_ms,
            candle_interval_ms=run.candle_interval_ms,
        ),
        events=(
            ConfigChanged(
                run_id=run.run_id,
                version=candidate.version,
                revision=revision,
                name=run.name,
                tick_interval_ms=run.tick_interval_ms,
                candle_interval_ms=run.candle_interval_ms,
                quote_grace_versions=view.quote_grace_versions,
                drinks=tuple(
                    (d, name, bool(on))
                    for d, name, on in zip(drink_ids, spec.names, spec.active.tolist(), strict=True)
                ),
                params=spec.params,
            ),
        ),
        ticks=(
            TickEntry(candidate.version, now_ms, "config", tick_prices(spec, candidate, drink_ids)),
        ),
        ring_window_ms=(
            None if window == view.spec.params.history_window_minutes else round(window * 60_000)
        ),
    )


async def current_revision(engine: AsyncEngine, run_id: int) -> int:
    """An empty PATCH's answer: no lock, no write, no transition (AC2)."""
    async with engine.connect() as conn:
        run = readable(await get_run(conn, run_id))
        return await latest_revision(conn, run.run_id)


async def write_draft_config(
    engine: AsyncEngine, run_id: int, patch: ConfigPatch, *, author: str
) -> int:
    """Merge `patch` into a draft run; the new revision, or the current one if nothing changed."""
    if _is_empty(patch):
        return await current_revision(engine, run_id)
    async with engine.begin() as conn:
        run = readable(await get_run(conn, run_id, lock=True))
        if run.status != "draft":
            raise RunNotDraft(f"run {run_id} is {run.status}, and not live in this process")
        merged = await _merged(conn, run, patch)
        if merged is None:
            return await latest_revision(conn, run_id)
        return await _record(conn, merged, author=author)


async def write_live_config(
    holder: MarketHolder, run_id: int, patch: ConfigPatch, *, author: str, clock: Clock
) -> int:
    """Merge `patch` into the live run as one engine transition (SD7); the new revision.

    A `step_quant` change holds every active slot's quoted price (SD9,
    `hold_quoted_prices`, its jumps cancelled); any other change leaves `y`
    alone. A patch that changes nothing returns the current revision and takes
    no transition.
    """
    engine = holder.engine
    if _is_empty(patch):
        return await current_revision(engine, run_id)

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id == run_id and view.spec is not None and view.state is not None
        now_ms = commit_stamp_ms(clock, view)
        async with engine.begin() as conn:
            run = readable(await get_run(conn, run_id, lock=True))
            merged = await _merged(conn, run, patch)
            if merged is None:
                return Outcome(result=await latest_revision(conn, run_id), view=view)
            params = Params.from_dict(merged.params)
            spec = dataclasses.replace(view.spec, params=params)
            state = view.state
            if params.step_quant != view.spec.params.step_quant:
                active = [i for i, on in enumerate(spec.active.tolist()) if on]
                state = hold_quoted_prices(view.spec, spec, state, active)
            revision = await _record(conn, merged, author=author)
            return await commit_transition(
                conn, view, merged, spec=spec, state=state, revision=revision, now_ms=now_ms
            )

    return await holder.mutate("config", step)


async def anchor_s0(holder: MarketHolder, run_id: int, *, author: str, clock: Clock) -> int:
    """Anchor every active drink's `s0` on the current prices (SD26); the new revision."""
    engine = holder.engine
    if holder.run_id != run_id:
        async with engine.connect() as conn:
            run = readable(await get_run(conn, run_id))
        raise RunNotLive(f"run {run_id} is {run.status}; anchor-s0 needs the live market")

    async def step(view: MarketView) -> Outcome[int]:
        assert view.run_id == run_id and view.spec is not None and view.state is not None
        now_ms = commit_stamp_ms(clock, view)
        spec = anchor_s0_to_current_y(view.spec, view.state.y)
        async with engine.begin() as conn:
            run = readable(await get_run(conn, run_id, lock=True))
            for drink_id, s0, active in zip(
                view.drink_ids, spec.s0.tolist(), spec.active.tolist(), strict=True
            ):
                if active:
                    await set_drink_s0(conn, drink_id, s0)
            revision = await append_revision(conn, run, author=author)
            return await commit_transition(
                conn, view, run, spec=spec, state=view.state, revision=revision, now_ms=now_ms
            )

    return await holder.mutate("config", step)

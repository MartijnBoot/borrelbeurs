"""The atomic order write and the earnings `GROUP BY` (T12).

AC2, AC11 (query half), AC13; D-10, D-12; SD12.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.codec import tick_prices
from app.db.engine_state import StaleState
from app.db.keys import create_key
from app.db.mapping import cents_from_quantised, spec_from_rows
from app.db.orders import (
    OrderLineInput,
    OrderWritten,
    StoredOrder,
    earnings_by_drink,
    find_order_by_key,
    write_order,
)
from app.db.runs import active_drinks, add_drink, create_draft_run, go_live
from app.db.session import create_engine
from exchange import EngineState, MarketSpec, Params, advance
from tests.engine.golden.scenarios import LIVE_CONFIG

SEED = 2024
T0 = 1_700_000_000_000

# UPDATE engine_state, INSERT "order", INSERT order_line (one multi-row statement),
# UPDATE "order" SET response (Phase 3 T18, when a receipt is given), INSERT price_tick.
# A new statement must be added here, so it cannot skip injection.
WRITE_ORDER_STATEMENTS = 5


def _receipt(order_id: int) -> dict[str, Any]:
    return {"order_id": order_id}


class Injected(Exception):
    """Raised by the listener in place of the Nth statement."""


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


async def _live(engine: AsyncEngine) -> tuple[int, MarketSpec, tuple[int, ...], EngineState]:
    """A live run holding the live config's six drinks, at version 0."""
    params = Params.from_dict(LIVE_CONFIG["params"])
    async with engine.begin() as conn:
        run_id = await create_draft_run(conn, params=params, run_seed=SEED)
        for slot, name in enumerate(LIVE_CONFIG["names"]):
            await add_drink(
                conn,
                run_id,
                name=name,
                slot=slot,
                p_min_cents=round(LIVE_CONFIG["p_min"][slot] * 100),
                p0_cents=round(LIVE_CONFIG["p0"][slot] * 100),
                p_max_cents=round(LIVE_CONFIG["p_max"][slot] * 100),
                a=LIVE_CONFIG["a"][slot],
                d=LIVE_CONFIG["d"][slot],
                s0=LIVE_CONFIG["s0"][slot],
                c=LIVE_CONFIG["c"][slot],
                bar_price_cents=round(LIVE_CONFIG["p0"][slot] * 100),
            )
    state = await go_live(engine, run_id, now_ms=T0)
    async with engine.connect() as conn:
        drinks = await active_drinks(conn, run_id)
    spec, drink_ids = spec_from_rows(drinks, params)
    return run_id, spec, drink_ids, state


def _order(
    spec: MarketSpec,
    state: EngineState,
    drink_ids: tuple[int, ...],
    qtys: dict[int, int],
    now_ms: int,
) -> tuple[EngineState, list[OrderLineInput]]:
    """The candidate state for `qtys` and its lines, priced at `state`'s displayed prices."""
    prices = tick_prices(spec, state, drink_ids)
    lines = [
        OrderLineInput(
            drink_id=drink_id,
            qty=qty,
            unit_price_cents=cents_from_quantised(prices[drink_id]["p_q"]),
            p_cont=prices[drink_id]["p_cont"],
        )
        for drink_id, qty in qtys.items()
    ]
    orders = np.array([float(qtys.get(drink_id, 0)) for drink_id in drink_ids])
    return advance(spec, state, now_ms=now_ms, orders=orders, run_seed=SEED).state, lines


async def _snapshot(engine: AsyncEngine, run_id: int) -> tuple[Any, ...]:
    """Every row count `write_order` touches, plus the whole `engine_state` row."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    'SELECT (SELECT count(*) FROM "order" WHERE run_id = :r),'
                    " (SELECT count(*) FROM order_line l"
                    '   JOIN "order" o USING (order_id) WHERE o.run_id = :r),'
                    " (SELECT count(*) FROM price_tick WHERE run_id = :r),"
                    " (SELECT row_to_json(e)::text FROM engine_state e WHERE run_id = :r)"
                ),
                {"r": run_id},
            )
        ).one()
    return tuple(row)


def test_write_order_issues_the_expected_statements(settings: Settings, database_url: str) -> None:
    """Pins the count the AC2 parametrisation covers."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        statements: list[str] = []

        def record(*args: Any) -> None:
            statements.append(args[2])

        try:
            run_id, spec, drink_ids, state = await _live(engine)
            candidate, lines = _order(spec, state, drink_ids, {drink_ids[0]: 2}, T0 + 1_000)
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            try:
                await write_order(
                    engine,
                    run_id=run_id,
                    idempotency_key="k-1",
                    expected_version=state.version,
                    state=candidate,
                    spec=spec,
                    drink_ids=drink_ids,
                    lines=lines,
                    wall_ts_ms=T0 + 1_000,
                    response=_receipt,
                )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record)
            assert len(statements) == WRITE_ORDER_STATEMENTS, statements
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_at", range(1, WRITE_ORDER_STATEMENTS + 1))
def test_a_failure_at_any_statement_writes_nothing(
    settings: Settings, database_url: str, fail_at: int
) -> None:
    """AC2: whichever statement fails, the order, lines, tick and state are as before."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        seen = 0

        def inject(*args: Any) -> None:
            nonlocal seen
            seen += 1
            if seen == fail_at:
                raise Injected(f"statement {fail_at}: {args[2]}")

        try:
            run_id, spec, drink_ids, state = await _live(engine)
            candidate, lines = _order(
                spec, state, drink_ids, {drink_ids[0]: 2, drink_ids[4]: 1}, T0 + 1_000
            )
            before = await _snapshot(engine, run_id)
            event.listen(engine.sync_engine, "before_cursor_execute", inject)
            try:
                with pytest.raises(Injected):
                    await write_order(
                        engine,
                        run_id=run_id,
                        idempotency_key="k-1",
                        expected_version=state.version,
                        state=candidate,
                        spec=spec,
                        drink_ids=drink_ids,
                        lines=lines,
                        wall_ts_ms=T0 + 1_000,
                        response=_receipt,
                    )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", inject)
            assert await _snapshot(engine, run_id) == before
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_two_orders_from_one_version_race_and_one_loses(
    settings: Settings, database_url: str
) -> None:
    """AC13: one commits with all its lines; the loser is `StaleState` and leaves nothing."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            wall = T0 + 1_000
            a_state, a_lines = _order(spec, state, drink_ids, {drink_ids[0]: 1}, wall)
            b_state, b_lines = _order(
                spec, state, drink_ids, {drink_ids[1]: 2, drink_ids[2]: 3}, wall
            )

            def attempt(key: str, candidate: EngineState, lines: list[OrderLineInput]) -> Any:
                return write_order(
                    engine,
                    run_id=run_id,
                    idempotency_key=key,
                    expected_version=state.version,
                    state=candidate,
                    spec=spec,
                    drink_ids=drink_ids,
                    lines=lines,
                    wall_ts_ms=wall,
                )

            results = await asyncio.gather(
                attempt("a", a_state, a_lines),
                attempt("b", b_state, b_lines),
                return_exceptions=True,
            )

            written = [r for r in results if isinstance(r, OrderWritten)]
            stale = [r for r in results if isinstance(r, StaleState)]
            assert len(written) == 1 and len(stale) == 1, results
            winner_lines = a_lines if isinstance(results[0], OrderWritten) else b_lines

            async with engine.connect() as conn:
                keys: list[str] = list(
                    (
                        await conn.execute(
                            text('SELECT idempotency_key FROM "order" WHERE run_id = :r'),
                            {"r": run_id},
                        )
                    ).scalars()
                )
                stored_lines = (
                    await conn.execute(
                        text("SELECT drink_id, qty FROM order_line ORDER BY drink_id")
                    )
                ).all()
            assert keys == ["a" if winner_lines is a_lines else "b"]
            assert [tuple(row) for row in stored_lines] == sorted(
                (line.drink_id, line.qty) for line in winner_lines
            )
            orders, line_count, ticks, _ = await _snapshot(engine, run_id)
            assert (orders, line_count, ticks) == (1, len(winner_lines), 2)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_ten_sequential_orders_are_all_present_with_their_lines(
    settings: Settings, database_url: str
) -> None:
    """AC13: in sequence, every order commits, each at the next version."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            expected: list[tuple[int, int, int, int]] = []
            for n in range(1, 11):
                wall = T0 + n * 1_000
                qtys = {drink_ids[n % 6]: n, drink_ids[(n + 3) % 6]: 1}
                candidate, lines = _order(spec, state, drink_ids, qtys, wall)
                written = await write_order(
                    engine,
                    run_id=run_id,
                    idempotency_key=f"k-{n}",
                    expected_version=state.version,
                    state=candidate,
                    spec=spec,
                    drink_ids=drink_ids,
                    lines=lines,
                    wall_ts_ms=wall,
                )
                assert written.version == n
                expected.extend(
                    (n, line.drink_id, line.qty, line.qty * line.unit_price_cents) for line in lines
                )
                state = candidate

            async with engine.connect() as conn:
                stored = (
                    await conn.execute(
                        text(
                            "SELECT o.version, l.drink_id, l.qty, l.line_total_cents"
                            ' FROM order_line l JOIN "order" o USING (order_id)'
                            " WHERE o.run_id = :r ORDER BY o.version, l.drink_id"
                        ),
                        {"r": run_id},
                    )
                ).all()
                sources: list[str] = list(
                    (
                        await conn.execute(
                            text(
                                "SELECT source FROM price_tick WHERE run_id = :r ORDER BY version"
                            ),
                            {"r": run_id},
                        )
                    ).scalars()
                )
            assert [tuple(row) for row in stored] == sorted(expected)
            assert sources == ["reset"] + ["order"] * 10
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_earnings_by_drink_equals_the_sum_of_the_lines(
    settings: Settings, database_url: str
) -> None:
    """AC11: the `GROUP BY` agrees with a row-by-row Python sum."""

    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            for n in range(1, 8):
                wall = T0 + n * 1_000
                qtys = {drink_ids[n % 6]: n, drink_ids[(n * 5) % 6]: 2}
                candidate, lines = _order(spec, state, drink_ids, qtys, wall)
                await write_order(
                    engine,
                    run_id=run_id,
                    idempotency_key=f"k-{n}",
                    expected_version=state.version,
                    state=candidate,
                    spec=spec,
                    drink_ids=drink_ids,
                    lines=lines,
                    wall_ts_ms=wall,
                )
                state = candidate

            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT l.drink_id, l.qty, l.line_total_cents"
                            ' FROM order_line l JOIN "order" o USING (order_id)'
                            " WHERE o.run_id = :r"
                        ),
                        {"r": run_id},
                    )
                ).all()
                earnings = await earnings_by_drink(conn, run_id)

            totals: dict[int, list[int]] = {}
            for drink_id, qty, line_total in rows:
                assert isinstance(drink_id, int) and isinstance(qty, int)
                assert isinstance(line_total, int)
                total = totals.setdefault(drink_id, [0, 0])
                total[0] += qty
                total[1] += line_total
            assert earnings == sorted((d, q, r) for d, (q, r) in totals.items())
            assert len(earnings) > 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_duplicate_idempotency_key_raises_and_writes_nothing(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            first, lines = _order(spec, state, drink_ids, {drink_ids[0]: 1}, T0 + 1_000)
            await write_order(
                engine,
                run_id=run_id,
                idempotency_key="same",
                expected_version=state.version,
                state=first,
                spec=spec,
                drink_ids=drink_ids,
                lines=lines,
                wall_ts_ms=T0 + 1_000,
            )
            second, lines = _order(spec, first, drink_ids, {drink_ids[1]: 1}, T0 + 2_000)
            before = await _snapshot(engine, run_id)

            with pytest.raises(IntegrityError, match="order_idempotency_key_key"):
                await write_order(
                    engine,
                    run_id=run_id,
                    idempotency_key="same",
                    expected_version=first.version,
                    state=second,
                    spec=spec,
                    drink_ids=drink_ids,
                    lines=lines,
                    wall_ts_ms=T0 + 2_000,
                )
            assert await _snapshot(engine, run_id) == before
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_line_naming_a_foreign_drink_raises_before_any_sql(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> None:
        engine = _engine(settings, database_url)
        statements: list[str] = []

        def record(*args: Any) -> None:
            statements.append(args[2])

        try:
            run_id, spec, drink_ids, state = await _live(engine)
            candidate, lines = _order(spec, state, drink_ids, {drink_ids[0]: 1}, T0 + 1_000)
            foreign = OrderLineInput(
                drink_id=max(drink_ids) + 1, qty=1, unit_price_cents=100, p_cont=1.0
            )
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            try:
                with pytest.raises(ValueError, match=str(foreign.drink_id)):
                    await write_order(
                        engine,
                        run_id=run_id,
                        idempotency_key="k-1",
                        expected_version=state.version,
                        state=candidate,
                        spec=spec,
                        drink_ids=drink_ids,
                        lines=[*lines, foreign],
                        wall_ts_ms=T0 + 1_000,
                    )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record)
            assert statements == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


# --- Phase 3 T18: the acting key, the stored receipt, lookup by key -------------


def test_the_actor_and_receipt_are_stored_and_found_by_key(
    settings: Settings, database_url: str
) -> None:
    async def scenario() -> tuple[OrderWritten, StoredOrder | None, StoredOrder | None, int]:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            async with engine.begin() as conn:
                key_id = await create_key(conn, label="Bar", role="bar", secret_hash="x")
            candidate, lines = _order(spec, state, drink_ids, {drink_ids[0]: 2}, T0 + 1_000)
            written = await write_order(
                engine,
                run_id=run_id,
                idempotency_key="k-receipt",
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                lines=lines,
                wall_ts_ms=T0 + 1_000,
                actor_key_id=key_id,
                response=lambda order_id: {"order_id": order_id, "total_cents": 1},
            )
            async with engine.connect() as conn:
                found = await find_order_by_key(conn, "k-receipt")
                missing = await find_order_by_key(conn, "k-absent")
            return written, found, missing, key_id
        finally:
            await engine.dispose()

    written, found, missing, key_id = asyncio.run(scenario())
    assert missing is None
    assert found is not None
    assert (found.order_id, found.version) == (written.order_id, written.version)
    assert found.actor_key_id == key_id
    assert found.response == {"order_id": written.order_id, "total_cents": 1}


def test_an_order_without_a_receipt_stores_none(settings: Settings, database_url: str) -> None:
    """Phase 2's callers pass neither; both columns stay NULL."""

    async def scenario() -> StoredOrder | None:
        engine = _engine(settings, database_url)
        try:
            run_id, spec, drink_ids, state = await _live(engine)
            candidate, lines = _order(spec, state, drink_ids, {drink_ids[0]: 1}, T0 + 1_000)
            await write_order(
                engine,
                run_id=run_id,
                idempotency_key="k-plain",
                expected_version=state.version,
                state=candidate,
                spec=spec,
                drink_ids=drink_ids,
                lines=lines,
                wall_ts_ms=T0 + 1_000,
            )
            async with engine.connect() as conn:
                return await find_order_by_key(conn, "k-plain")
        finally:
            await engine.dispose()

    found = asyncio.run(scenario())
    assert found is not None
    assert (found.actor_key_id, found.response) == (None, None)

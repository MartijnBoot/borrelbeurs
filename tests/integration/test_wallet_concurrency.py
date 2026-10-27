"""Concurrent wallet actions never break the ledger (B-05 T11: SD23; AC23, AC46).

A seeded random sequence of top-ups, reversals, moves and deletes over five
wallets runs in concurrent batches (`asyncio.gather`), each action its own
transaction as the routes run it. After every batch:

- no wallet's balance is below zero;
- each live wallet's balance, as the kassa reads it, equals the SQL sum of its entries;
- each top-up is reversed at most once, by minus its amount, on its own wallet;
- every deleted wallet's entries sum to zero.

Refusals the rules expect are counted; any other exception fails. This test
changes no source: one failing means the locking or a transaction is wrong.
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from collections.abc import Awaitable, Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.security import issue_key
from app.core.config import Settings
from app.db import wallets
from app.db.session import create_engine
from app.runtime import wallets as actions

T0 = 1_759_312_800_000
SEED = 20261025
OPERATIONS = 240
BATCH = 8
POOL = 5

EXPECTED = (
    wallets.WalletNotFound,
    wallets.WalletDeleted,
    wallets.AlreadyReversed,
    wallets.InsufficientBalance,
    wallets.NothingToMove,
    actions.TopupNotFound,
)


async def _rows(engine: AsyncEngine, sql: str) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        return [tuple(row) for row in await conn.execute(text(sql))]


async def _live(engine: AsyncEngine) -> list[int]:
    rows = await _rows(engine, "SELECT wallet_id FROM wallet WHERE deleted_at IS NULL")
    return [int(row[0]) for row in rows]


async def _check(engine: AsyncEngine) -> None:
    sums = {
        int(row[0]): (int(row[1]), bool(row[2]))
        for row in await _rows(
            engine,
            "SELECT w.wallet_id, coalesce(sum(e.amount_cents), 0), w.deleted_at IS NOT NULL"
            " FROM wallet w LEFT JOIN wallet_entry e USING (wallet_id) GROUP BY w.wallet_id",
        )
    }
    assert all(total >= 0 for total, _ in sums.values()), sums
    assert all(total == 0 for total, deleted in sums.values() if deleted), sums
    async with engine.connect() as conn:
        for wallet_id, (total, deleted) in sums.items():
            if not deleted:
                assert await wallets.balance(conn, wallet_id) == total
    wrong_reversals = await _rows(
        engine,
        "SELECT r.entry_id FROM wallet_entry r JOIN wallet_entry t"
        " ON t.entry_id = r.reverses_entry_id WHERE r.kind = 'reversal'"
        " AND (t.kind <> 'topup' OR r.amount_cents <> -t.amount_cents"
        " OR r.wallet_id <> t.wallet_id)",
    )
    twice = await _rows(
        engine,
        "SELECT reverses_entry_id FROM wallet_entry WHERE reverses_entry_id IS NOT NULL"
        " GROUP BY reverses_entry_id HAVING count(*) > 1",
    )
    assert (wrong_reversals, twice) == ([], [])


def _plan(
    rng: random.Random,
    engine: AsyncEngine,
    *,
    actor: actions.Actor,
    live: list[int],
    topups: list[int],
    keys: Iterator[str],
    now_ms: int,
) -> tuple[str, Awaitable[Any]]:
    """One random action over `live` wallets and the `topups` booked so far."""
    kind = rng.choices(["topup", "reverse", "move", "delete"], weights=[45, 30, 18, 7])[0]
    wallet_id = rng.choice(live)
    if kind == "reverse" and topups:
        return kind, actions.reverse(
            engine,
            entry_id=rng.choice(topups),
            idempotency_key=next(keys),
            actor=actor,
            now_ms=now_ms,
        )
    if kind == "move":
        return kind, actions.move(
            engine,
            wallet_id=wallet_id,
            from_wallet_id=rng.choice(live),
            idempotency_key=next(keys),
            actor=actor,
            now_ms=now_ms,
        )
    if kind == "delete":
        return kind, actions.delete(engine, wallet_id, actor=actor, now_ms=now_ms)
    return "topup", actions.top_up(
        engine,
        wallet_id=wallet_id,
        amount_cents=rng.randrange(1000, 10_001, 500),
        idempotency_key=next(keys),
        actor=actor,
        now_ms=now_ms,
    )


def test_a_random_concurrent_sequence_keeps_every_balance_at_or_above_zero(
    settings: Settings, database_url: str
) -> None:
    """AC23, AC46."""
    rng = random.Random(SEED)
    keys = iter(f"k-conc-{n:06d}" for n in range(10 * OPERATIONS))
    names = iter(f"Speler {n}" for n in range(10 * OPERATIONS))

    async def scenario() -> Counter[str]:
        engine = create_engine(settings.model_copy(update={"database_url": database_url}))
        outcomes: Counter[str] = Counter()
        topups: list[int] = []
        try:
            async with engine.begin() as conn:
                key_id = (await issue_key(conn, role="kassa", label="Kassa")).key_id
            actor = actions.Actor(key_id=key_id, label="Kassa")
            for batch in range(OPERATIONS // BATCH):
                for _ in range(POOL - len(await _live(engine))):
                    async with engine.begin() as conn:
                        await wallets.create_wallet(
                            conn, name=next(names), cookie_hash=next(keys), now_ms=T0
                        )
                live = await _live(engine)
                planned = [
                    _plan(
                        rng,
                        engine,
                        actor=actor,
                        live=live,
                        topups=topups,
                        keys=keys,
                        now_ms=T0 + batch * 1000,
                    )
                    for _ in range(BATCH)
                ]
                results = await asyncio.gather(
                    *(action for _, action in planned), return_exceptions=True
                )
                for (kind, _), result in zip(planned, results, strict=True):
                    if isinstance(result, EXPECTED):
                        outcomes[f"{kind}:{type(result).__name__}"] += 1
                    elif isinstance(result, BaseException):
                        raise AssertionError(f"{kind} raised {result!r}") from result
                    else:
                        outcomes[kind] += 1
                        if kind == "topup":
                            topups.append(result.entry.entry_id)
                await _check(engine)
            return outcomes
        finally:
            await engine.dispose()

    outcomes = asyncio.run(scenario())

    assert sum(outcomes.values()) == OPERATIONS
    # Anti-vacuity: every kind happened, and a reversal was refused as a repeat and as
    # on a deleted wallet. These four actions cannot reach `insufficient_balance`: a
    # reversal removes exactly its own top-up, and the one other debit, a move out,
    # deletes the wallet. Its refusal is pinned in `tests/api/test_kassa_corrections.py`.
    for kind in ("topup", "reverse", "move", "delete"):
        assert outcomes[kind] > 0, outcomes
    assert outcomes["reverse:AlreadyReversed"] > 0, outcomes
    assert outcomes["reverse:WalletDeleted"] > 0, outcomes

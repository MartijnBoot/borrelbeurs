"""The in-memory earnings aggregate per `drink_id` (T7).

AC17 (pure in-memory reads); SD12.
"""

from __future__ import annotations

import pytest

from app.runtime.earnings import DrinkEarnings, EarningsAggregate

LINES = [(7, 2, 520), (3, 1, 150), (7, 1, 270), (9, 4, 0), (3, 3, 450)]


def test_add_lines_accumulates() -> None:
    earnings = EarningsAggregate.from_rows([])

    earnings.add_lines(LINES[:2])
    earnings.add_lines(LINES[2:])

    assert earnings.snapshot() == {
        7: DrinkEarnings(qty=3, revenue_cents=790),
        3: DrinkEarnings(qty=4, revenue_cents=600),
        9: DrinkEarnings(qty=4, revenue_cents=0),
    }


def test_a_fresh_aggregate_from_rows_equals_the_incremental_one() -> None:
    """The boot `GROUP BY` and the post-commit updates agree."""
    incremental = EarningsAggregate.from_rows([(7, 1, 260)])
    for line in LINES:
        incremental.add_lines([line])

    grouped: dict[int, tuple[int, int]] = {7: (1, 260)}
    for drink_id, qty, cents in LINES:
        q, c = grouped.get(drink_id, (0, 0))
        grouped[drink_id] = (q + qty, c + cents)
    fresh = EarningsAggregate.from_rows([(d, q, c) for d, (q, c) in grouped.items()])

    assert fresh.snapshot() == incremental.snapshot()


def test_the_snapshot_cannot_be_mutated() -> None:
    earnings = EarningsAggregate.from_rows([(7, 1, 260)])
    snapshot = earnings.snapshot()

    with pytest.raises(TypeError):
        snapshot[7] = DrinkEarnings(qty=0, revenue_cents=0)  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot[7].qty = 5  # type: ignore[misc]


def test_a_snapshot_does_not_move_when_later_lines_arrive() -> None:
    earnings = EarningsAggregate.from_rows([(7, 1, 260)])
    before = earnings.snapshot()

    earnings.add_lines([(7, 1, 260)])

    assert before[7] == DrinkEarnings(qty=1, revenue_cents=260)
    assert earnings.snapshot()[7] == DrinkEarnings(qty=2, revenue_cents=520)


def test_a_drink_listed_twice_in_from_rows_raises() -> None:
    with pytest.raises(ValueError, match="7"):
        EarningsAggregate.from_rows([(7, 1, 260), (7, 2, 520)])

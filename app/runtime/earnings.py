"""The earnings aggregate: quantity sold and revenue per `drink_id` (SD12).

Rebuilt by one `GROUP BY` over `order_line` at boot, then updated after each
committed order, so reading earnings is a pure in-memory read (AC17). Revenue
is stored only as `order_line.line_total_cents` (AC11); this is a cache of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class DrinkEarnings:
    qty: int
    revenue_cents: int


class EarningsAggregate:
    def __init__(self) -> None:
        self._by_drink: dict[int, DrinkEarnings] = {}

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[int, int, int]]) -> EarningsAggregate:
        """From `(drink_id, qty, revenue_cents)` rows, one per drink."""
        aggregate = cls()
        for drink_id, qty, revenue_cents in rows:
            if drink_id in aggregate._by_drink:
                raise ValueError(f"earnings rows list drink {drink_id} twice")
            aggregate._by_drink[drink_id] = DrinkEarnings(qty=qty, revenue_cents=revenue_cents)
        return aggregate

    def add_lines(self, lines: Iterable[tuple[int, int, int]]) -> None:
        """Add `(drink_id, qty, line_total_cents)` lines. Call only after the order committed."""
        for drink_id, qty, line_total_cents in lines:
            current = self._by_drink.get(drink_id, DrinkEarnings(qty=0, revenue_cents=0))
            self._by_drink[drink_id] = DrinkEarnings(
                qty=current.qty + qty, revenue_cents=current.revenue_cents + line_total_cents
            )

    def snapshot(self) -> Mapping[int, DrinkEarnings]:
        """A read-only copy: later lines do not change it."""
        return MappingProxyType(dict(self._by_drink))

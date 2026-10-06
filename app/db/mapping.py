"""Drink rows to the engine's positional `MarketSpec`, and engine prices back to cents.

The engine knows drinks by array position; the database knows them by
`drink_id` (D-24). This module is the one translation between the two:
`spec_from_rows` sorts by `slot` and returns the `drink_ids` in that same
order, so position `i` of every engine array is `drink_ids[i]`.

Prices are stored as integer cents (PD3). `cents / 100` is the correctly
rounded double nearest the decimal, the same float `json.loads` gives for v1's
`2.6`, so a spec built from the database is bitwise the spec built from the
file (AC19). The way back, `cents_from_quantised`, is exact because
`step_quant` is a multiple of 0.01 (SD7).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from exchange import DrinkSpec, MarketSpec, Params


@dataclass(frozen=True)
class DrinkRow:
    """One `drink` row as the repositories return it."""

    drink_id: int
    slot: int
    name: str
    p_min_cents: int
    p0_cents: int
    p_max_cents: int
    a: float
    d: float
    s0: float
    c: float
    bar_price_cents: int
    removed: bool = False


def spec_from_rows(
    drinks: Iterable[DrinkRow], params: Params
) -> tuple[MarketSpec, tuple[int, ...]]:
    """The market in slot order, and the `drink_id` at each position.

    A removed row keeps its slot as an inactive one (SD15).
    """
    ordered = sorted(drinks, key=lambda row: row.slot)
    spec = MarketSpec.from_drinks(
        (
            DrinkSpec(
                name=row.name,
                p_min=row.p_min_cents / 100,
                p_max=row.p_max_cents / 100,
                p0=row.p0_cents / 100,
                a=row.a,
                d=row.d,
                s0=row.s0,
                c=row.c,
                active=not row.removed,
            )
            for row in ordered
        ),
        params,
    )
    return spec, tuple(row.drink_id for row in ordered)


def params_to_json(params: Params) -> dict[str, Any]:
    """`params` as a JSON object that `Params.from_dict` reads back equal."""
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in dataclasses.asdict(params).items()
    }


def cents_from_quantised(p_q: float) -> int:
    """A quantised engine price as integer cents (SD7)."""
    return round(p_q * 100)

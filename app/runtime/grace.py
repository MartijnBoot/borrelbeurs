"""The grace rule (Phase 3 SD18, refining ADR 0008): which quoted price an order is charged.

For each line, `live` is the drink's current charged price (`price_cents`,
SD24) and `step` is `step_quant` in cents:

- `unit_price_cents == live`: charge it, whatever the quote's age. The customer
  pays exactly what was shown.
- `|unit_price_cents - live| <= step` and `current_version - quote_version <=
  grace`: honour the quoted `unit_price_cents`.
- otherwise the whole order is rejected with every line's live price and the
  current version. One line outside grace rejects all of them.

So a charged line is always charged its quoted price: "the price displayed is
the price charged, or the order is rejected". Pure: no clock, no I/O; the order
path (T18) calls it under the holder's lock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QuotedLine:
    """One order line as the client sent it: the price it was shown."""

    drink_id: int
    qty: int
    unit_price_cents: int


@dataclass(frozen=True)
class Charged:
    """Every line accepted; `lines` carry the charged unit price, which is the quoted one."""

    lines: tuple[QuotedLine, ...]


@dataclass(frozen=True)
class PriceChanged:
    """The order is rejected whole: each line's live price, and the current version."""

    version: int
    prices: Mapping[int, int]


def step_cents_from(step_quant: float) -> int:
    """`step_quant` as whole cents, or `ValueError` if it is not a positive whole number of them.

    SD24's assertion rests on `price_cents` being a multiple of the step, which
    holds only if the step itself is whole cents (plan R13).
    """
    cents = round(step_quant * 100)
    if cents <= 0 or abs(step_quant * 100 - cents) > 1e-9:
        raise ValueError(f"step_quant {step_quant!r} is not a positive whole number of cents")
    return cents


def judge(
    lines: Sequence[QuotedLine],
    live_cents: Mapping[int, int],
    *,
    step_cents: int,
    current_version: int,
    quote_version: int,
    grace_versions: int,
) -> Charged | PriceChanged:
    """SD18 over the whole order. `live_cents` must hold every line's drink."""
    if quote_version > current_version:
        raise ValueError(
            f"quote_version {quote_version} is ahead of version {current_version}; "
            "the order path rejects that before judging (SD17)"
        )
    for drink_id, cents in live_cents.items():
        if cents % step_cents != 0:
            raise AssertionError(
                f"drink {drink_id}'s live price {cents} is not a multiple of the "
                f"{step_cents}-cent step (SD24)"
            )

    age = current_version - quote_version

    def honoured(line: QuotedLine) -> bool:
        live = live_cents[line.drink_id]
        if line.unit_price_cents == live:
            return True
        return abs(line.unit_price_cents - live) <= step_cents and age <= grace_versions

    if all(honoured(line) for line in lines):
        return Charged(lines=tuple(lines))
    return PriceChanged(
        version=current_version,
        prices={line.drink_id: live_cents[line.drink_id] for line in lines},
    )

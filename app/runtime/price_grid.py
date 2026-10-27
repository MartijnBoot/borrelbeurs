"""Price bounds on the Prijsstap grid (B-07 SD1, SD3, SD4; plan PD1, PD2).

**On the grid (SD1)** is decided in whole cents: `cents % step_cents == 0`, with
`step_cents = round(step_quant * 100)`. The step is validated as whole cents
(`config_patch._whole_cents`), so the rounding is exact. 0 is always on the
grid. `grid_faults` gives one fault per off-grid value, naming its two grid
neighbours: "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30."

**The move inward (SD3)** takes any frozen dataclass with `name`, `slot` and
the three prices (`DrinkRow`, `ImportedDrink`): Minimumprijs up to the next
multiple, Maximumprijs down to the previous one, a bound on the grid left as it
is. The rows come back in input order; the moves in slot order, Minimum before
Maximum. The Startprijs is never moved (SD2).

**A collision (SD4).** Every returned row must still satisfy
`p_min < p0 < p_max`. If any does not, `BoundsCollision` (422
`bounds_collision`) carries one fault on `loc` whose message is every such
drink's sentence, in slot order, joined by a space (PD2): one joined fault,
because the web keeps one message per field.

This module is a leaf (the stdlib and `app.runtime.config_patch`), so `app/db`
and `app/cli` can move bounds by the same rule as `app/runtime/config.py`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol, TypeVar

from pydantic import JsonValue

from app.runtime.config_patch import InvalidConfig

BoundField = Literal["p_min_cents", "p_max_cents"]


class BoundsCollision(InvalidConfig):
    """A move inward left a drink with no room between its bounds (SD4)."""

    code = "bounds_collision"


class PricedRow(Protocol):
    """A frozen dataclass row with a drink's name, slot and three prices in cents."""

    __dataclass_fields__: ClassVar[dict[str, Any]]

    @property
    def name(self) -> str: ...
    @property
    def slot(self) -> int: ...
    @property
    def p_min_cents(self) -> int: ...
    @property
    def p0_cents(self) -> int: ...
    @property
    def p_max_cents(self) -> int: ...


Row = TypeVar("Row", bound=PricedRow)


@dataclass(frozen=True)
class BoundMove:
    """One bound moved inward: `field` of drink `name` from `old_cents` to `new_cents`."""

    name: str
    field: BoundField
    old_cents: int
    new_cents: int


def step_cents(step_quant: float) -> int:
    """The Prijsstap in whole cents: `0.1` gives `10`."""
    return round(step_quant * 100)


def euro_text(cents: int) -> str:
    """Cents as the page writes them: `124` gives `"1,24"` (the web's `centsText`)."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros},{rest:02d}"


def neighbours(cents: int, step: int) -> tuple[int, int]:
    """The grid points either side of an off-grid `cents`."""
    lower = cents // step * step
    return lower, lower + step


def grid_message(cents: int, step: int) -> str:
    """SD1's refusal for an off-grid `cents`."""
    lower, upper = neighbours(cents, step)
    return (
        f"Moet een veelvoud van de Prijsstap ({euro_text(step)}) zijn: "
        f"{euro_text(lower)} of {euro_text(upper)}."
    )


def grid_faults(
    values: Mapping[str, int], step: int, *, loc: Sequence[str]
) -> list[dict[str, JsonValue]]:
    """One fault per off-grid value, at `[*loc, field]`; empty when all are on the grid."""
    return [
        {"loc": [*loc, field], "msg": grid_message(cents, step)}
        for field, cents in values.items()
        if cents % step != 0
    ]


def _collision(row: PricedRow) -> str | None:
    bounds = f"{euro_text(row.p_min_cents)}–{euro_text(row.p_max_cents)}"  # noqa: RUF001 -- an en dash
    if row.p_min_cents >= row.p_max_cents:
        return f"Past niet bij {row.name}: de grenzen worden {bounds}."
    if not row.p_min_cents < row.p0_cents < row.p_max_cents:
        return (
            f"Past niet bij {row.name}: de grenzen worden {bounds} "
            f"en de Startprijs {euro_text(row.p0_cents)} valt daarbuiten."
        )
    return None


def move_inward(
    drinks: Sequence[Row], step: int, *, loc: Sequence[str]
) -> tuple[list[Row], list[BoundMove]]:
    """`drinks` with every bound moved inward onto `step`, and the moves (SD3).

    Raises `BoundsCollision` on `loc` when a returned row breaks
    `p_min < p0 < p_max` (SD4), naming every such drink.
    """
    moved: list[Row] = []
    moves: list[tuple[int, BoundMove]] = []
    for row in drinks:
        p_min = -(-row.p_min_cents // step) * step
        p_max = row.p_max_cents // step * step
        if p_min != row.p_min_cents:
            moves.append((row.slot, BoundMove(row.name, "p_min_cents", row.p_min_cents, p_min)))
        if p_max != row.p_max_cents:
            moves.append((row.slot, BoundMove(row.name, "p_max_cents", row.p_max_cents, p_max)))
        moved.append(dataclasses.replace(row, p_min_cents=p_min, p_max_cents=p_max))
    sentences = [
        sentence
        for row in sorted(moved, key=lambda r: r.slot)
        if (sentence := _collision(row)) is not None
    ]
    if sentences:
        joined = " ".join(sentences)
        raise BoundsCollision(joined, extra={"faults": [{"loc": list(loc), "msg": joined}]})
    # Stable: a drink's Minimum was appended before its Maximum.
    return moved, [move for _, move in sorted(moves, key=lambda pair: pair[0])]

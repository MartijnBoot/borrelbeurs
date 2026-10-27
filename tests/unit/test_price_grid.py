"""Price bounds on the Prijsstap grid (B-07 T1: AC1, AC6, AC8 as pure functions).

The Dutch texts are the spec's own (SD1, SD4); `grid.test.ts` pins the same
strings on the web, so the two sides cannot drift (PD8).
"""

from __future__ import annotations

import pytest

from app.cli.v1_files import ImportedDrink
from app.db.mapping import DrinkRow
from app.runtime.price_grid import (
    BoundMove,
    BoundsCollision,
    euro_text,
    grid_faults,
    grid_message,
    move_inward,
    neighbours,
    step_cents,
)

LOC = ("body", "params", "step_quant")


def _row(name: str, slot: int, p_min: int, p0: int, p_max: int) -> DrinkRow:
    return DrinkRow(
        drink_id=slot + 1,
        slot=slot,
        name=name,
        p_min_cents=p_min,
        p0_cents=p0,
        p_max_cents=p_max,
        a=10.0,
        d=0.6,
        s0=8.0,
        c=0.4,
        bar_price_cents=p0,
    )


def test_step_cents_is_the_step_in_whole_cents() -> None:
    assert step_cents(0.1) == 10
    assert step_cents(0.25) == 25
    assert step_cents(0.05) == 5
    assert step_cents(5.0) == 500


def test_euro_text_is_the_web_spelling() -> None:
    assert euro_text(124) == "1,24"
    assert euro_text(10) == "0,10"
    assert euro_text(0) == "0,00"
    assert euro_text(500) == "5,00"


@pytest.mark.parametrize(
    ("cents", "step", "message"),
    [
        (124, 10, "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30."),
        (160, 25, "Moet een veelvoud van de Prijsstap (0,25) zijn: 1,50 of 1,75."),
    ],
)
def test_an_off_grid_value_is_refused_with_its_two_neighbours(
    cents: int, step: int, message: str
) -> None:
    assert grid_message(cents, step) == message
    assert grid_faults({"p_min_cents": cents}, step, loc=("body",)) == [
        {"loc": ["body", "p_min_cents"], "msg": message}
    ]


@pytest.mark.parametrize(("cents", "step"), [(120, 10), (0, 10), (150, 25), (175, 25), (0, 25)])
def test_an_on_grid_value_is_accepted(cents: int, step: int) -> None:
    assert grid_faults({"p_min_cents": cents, "p_max_cents": cents}, step, loc=("body",)) == []


def test_one_fault_per_off_grid_value() -> None:
    faults = grid_faults({"p_min_cents": 124, "p_max_cents": 300}, 10, loc=("body",))
    assert [f["loc"] for f in faults] == [["body", "p_min_cents"]]
    faults = grid_faults({"p_min_cents": 124, "p_max_cents": 305}, 10, loc=("body",))
    assert [f["loc"] for f in faults] == [["body", "p_min_cents"], ["body", "p_max_cents"]]


def test_neighbours_bracket_the_value() -> None:
    assert neighbours(124, 10) == (120, 130)
    assert neighbours(160, 25) == (150, 175)
    assert neighbours(3, 10) == (0, 10)


def test_minimum_moves_up_and_maximum_moves_down() -> None:
    rows, moves = move_inward([_row("Bier", 0, 160, 200, 310)], 25, loc=LOC)
    assert (rows[0].p_min_cents, rows[0].p0_cents, rows[0].p_max_cents) == (175, 200, 300)
    assert moves == [
        BoundMove("Bier", "p_min_cents", 160, 175),
        BoundMove("Bier", "p_max_cents", 310, 300),
    ]


def test_a_bound_on_the_grid_stays() -> None:
    row = _row("Wijn", 0, 150, 220, 400)
    rows, moves = move_inward([row], 25, loc=LOC)
    assert rows == [row]
    assert moves == []


def test_only_the_bounds_change() -> None:
    row = _row("Bier", 0, 124, 201, 333)
    rows, _ = move_inward([row], 10, loc=LOC)
    assert rows[0] == DrinkRow(**{**vars(row), "p_min_cents": 130, "p_max_cents": 330})


def test_moves_are_in_slot_order_minimum_before_maximum_rows_in_input_order() -> None:
    late = _row("Fris", 2, 105, 150, 255)
    early = _row("Bier", 0, 124, 200, 333)
    rows, moves = move_inward([late, early], 10, loc=LOC)
    assert [r.name for r in rows] == ["Fris", "Bier"]
    assert moves == [
        BoundMove("Bier", "p_min_cents", 124, 130),
        BoundMove("Bier", "p_max_cents", 333, 330),
        BoundMove("Fris", "p_min_cents", 105, 110),
        BoundMove("Fris", "p_max_cents", 255, 250),
    ]


def test_startprijs_outside_the_moved_bounds_is_a_collision() -> None:
    with pytest.raises(BoundsCollision) as caught:
        move_inward([_row("Bier", 0, 110, 122, 280)], 25, loc=LOC)
    sentence = (
        "Past niet bij Bier: de grenzen worden 1,25–2,75 en de Startprijs 1,22 valt daarbuiten."  # noqa: RUF001
    )
    assert str(caught.value) == sentence
    assert caught.value.status_code == 422
    assert caught.value.code == "bounds_collision"
    assert caught.value.extra == {"faults": [{"loc": list(LOC), "msg": sentence}]}


def test_bounds_that_meet_or_cross_are_a_collision() -> None:
    with pytest.raises(BoundsCollision) as caught:
        move_inward([_row("Fris", 0, 160, 170, 180)], 50, loc=LOC)
    assert str(caught.value) == "Past niet bij Fris: de grenzen worden 2,00–1,50."  # noqa: RUF001


def test_two_collisions_join_into_one_fault_in_slot_order() -> None:
    fris = _row("Fris", 3, 160, 170, 180)
    bier = _row("Bier", 1, 110, 122, 280)
    ok = _row("Wijn", 0, 100, 200, 300)
    with pytest.raises(BoundsCollision) as caught:
        move_inward([fris, ok, bier], 25, loc=("body", "copy_from_run_id"))
    joined = (
        "Past niet bij Bier: de grenzen worden 1,25–2,75 en de Startprijs 1,22 valt daarbuiten. "  # noqa: RUF001
        "Past niet bij Fris: de grenzen worden 1,75–1,75."  # noqa: RUF001
    )
    assert caught.value.extra == {"faults": [{"loc": ["body", "copy_from_run_id"], "msg": joined}]}


def test_an_unmoved_drink_out_of_order_is_still_a_collision() -> None:
    # PD3: every drink handed in is checked, moved or not.
    with pytest.raises(BoundsCollision, match="Past niet bij Bier"):
        move_inward([_row("Bier", 0, 200, 100, 300)], 10, loc=LOC)


def test_an_imported_drink_is_moved_the_same_way() -> None:
    drink = ImportedDrink(
        name="Bier",
        slot=0,
        p_min_cents=124,
        p0_cents=200,
        p_max_cents=300,
        a=10.0,
        d=0.6,
        s0=8.0,
        c=0.4,
        bar_price_cents=200,
    )
    rows, moves = move_inward([drink], 10, loc=LOC)
    assert isinstance(rows[0], ImportedDrink)
    assert rows[0].p_min_cents == 130
    assert moves == [BoundMove("Bier", "p_min_cents", 124, 130)]

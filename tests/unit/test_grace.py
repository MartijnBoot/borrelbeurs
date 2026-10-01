"""The grace rule, pure (Phase 3 T5: AC10, AC11 pure halves; SD18; SD24's step assertion)."""

from __future__ import annotations

import itertools

import pytest

from app.runtime.grace import Charged, PriceChanged, QuotedLine, judge, step_cents_from

STEP = 10  # step_quant 0.10
GRACE = 2
CURRENT = 1_000
LIVE = 260
OTHER_DRINK, OTHER_LIVE = 8, 150

DELTAS = (0, STEP, -STEP, STEP + 1, -(STEP + 1), 2 * STEP, -2 * STEP)
AGES = (0, GRACE, GRACE + 1, 1_000)


def _judge(lines: list[QuotedLine], *, age: int) -> Charged | PriceChanged:
    return judge(
        lines,
        {7: LIVE, OTHER_DRINK: OTHER_LIVE},
        step_cents=STEP,
        current_version=CURRENT,
        quote_version=CURRENT - age,
        grace_versions=GRACE,
    )


def _sd18(delta: int, age: int) -> bool:
    """SD18's three bullets, written out independently of the code under test."""
    if delta == 0:
        return True
    return abs(delta) <= STEP and age <= GRACE


@pytest.mark.parametrize(("delta", "age"), list(itertools.product(DELTAS, AGES)))
def test_each_sd18_branch(delta: int, age: int) -> None:
    """AC10 / AC11 (pure): charged at the quoted price, or rejected with the live price."""
    quoted = QuotedLine(drink_id=7, qty=2, unit_price_cents=LIVE + delta)

    outcome = _judge([quoted], age=age)

    if _sd18(delta, age):
        assert outcome == Charged(lines=(quoted,))
    else:
        assert outcome == PriceChanged(version=CURRENT, prices={7: LIVE})


def test_the_table_reaches_every_branch() -> None:
    """Anti-vacuity: equal-at-any-age, honoured, and rejected all occur."""
    outcomes = {(d == 0, _sd18(d, a)) for d, a in itertools.product(DELTAS, AGES)}

    assert outcomes == {(True, True), (False, True), (False, False)}


@pytest.mark.parametrize("age", AGES)
def test_an_unchanged_price_is_charged_at_any_age(age: int) -> None:
    """The refinement: a quote held over many 1 Hz ticks at an unchanged price is not a 409."""
    quoted = QuotedLine(drink_id=7, qty=1, unit_price_cents=LIVE)

    assert _judge([quoted], age=age) == Charged(lines=(quoted,))


def test_a_charged_line_is_charged_its_quoted_price_not_the_live_one() -> None:
    quoted = QuotedLine(drink_id=7, qty=3, unit_price_cents=LIVE - STEP)

    outcome = _judge([quoted], age=1)

    assert isinstance(outcome, Charged)
    assert outcome.lines[0].unit_price_cents == LIVE - STEP


def test_one_line_outside_grace_rejects_the_whole_order() -> None:
    good = QuotedLine(drink_id=OTHER_DRINK, qty=1, unit_price_cents=OTHER_LIVE)
    bad = QuotedLine(drink_id=7, qty=1, unit_price_cents=LIVE + 2 * STEP)

    outcome = _judge([good, bad], age=0)

    assert outcome == PriceChanged(version=CURRENT, prices={OTHER_DRINK: OTHER_LIVE, 7: LIVE})


def test_a_live_price_off_the_step_trips_the_assertion() -> None:
    """SD24: `price_cents` is the step track, so a non-multiple is a bug, not a price."""
    with pytest.raises(AssertionError, match="not a multiple"):
        judge(
            [QuotedLine(drink_id=7, qty=1, unit_price_cents=265)],
            {7: 265},
            step_cents=STEP,
            current_version=CURRENT,
            quote_version=CURRENT,
            grace_versions=GRACE,
        )


def test_a_quote_from_the_future_is_refused() -> None:
    """SD17 rejects it with 422 before judging; reaching here would be a bug."""
    with pytest.raises(ValueError, match="ahead"):
        _judge([QuotedLine(drink_id=7, qty=1, unit_price_cents=LIVE)], age=-1)


@pytest.mark.parametrize(("step_quant", "cents"), [(0.10, 10), (0.05, 5), (0.01, 1), (0.5, 50)])
def test_step_cents_from_a_whole_number_of_cents(step_quant: float, cents: int) -> None:
    assert step_cents_from(step_quant) == cents


@pytest.mark.parametrize("step_quant", [0.025, 0.001, 0.0, -0.1])
def test_step_cents_from_rejects_a_fractional_or_non_positive_step(step_quant: float) -> None:
    with pytest.raises(ValueError, match="whole number of cents"):
        step_cents_from(step_quant)

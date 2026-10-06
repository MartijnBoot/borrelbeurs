"""Drink rows to the engine's positional `MarketSpec`, and engine prices to cents (T5).

AC14 (mapping half), SD7 (`cents_from_quantised`), PD3.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from app.db.mapping import DrinkRow, cents_from_quantised, params_to_json, spec_from_rows
from exchange import MarketSpec, Params
from exchange.pricing import quantize_step
from tests.engine.golden.replay import spec_from_config
from tests.engine.golden.scenarios import LIVE_CONFIG

ARRAYS = ("p_min", "p_max", "p0", "a", "d", "s0", "c")


def _rows_from_live_config() -> list[DrinkRow]:
    """The live config as the import stores it: euros as exact cents, ids from 101."""
    return [
        DrinkRow(
            drink_id=101 + slot,
            slot=slot,
            name=name,
            p_min_cents=round(LIVE_CONFIG["p_min"][slot] * 100),
            p0_cents=round(LIVE_CONFIG["p0"][slot] * 100),
            p_max_cents=round(LIVE_CONFIG["p_max"][slot] * 100),
            a=LIVE_CONFIG["a"][slot],
            d=LIVE_CONFIG["d"][slot],
            s0=LIVE_CONFIG["s0"][slot],
            c=LIVE_CONFIG["c"][slot],
            bar_price_cents=round(LIVE_CONFIG["p0"][slot] * 100),
        )
        for slot, name in enumerate(LIVE_CONFIG["names"])
    ]


def assert_specs_equal(left: MarketSpec, right: MarketSpec) -> None:
    """`MarketSpec` is `eq=False`; compare it field by field, bitwise."""
    assert left.names == right.names
    for key in ARRAYS:
        a, b = getattr(left, key), getattr(right, key)
        assert a.dtype == b.dtype == np.float64, key
        assert a.view(np.uint64).tobytes() == b.view(np.uint64).tobytes(), key
    assert left.params == right.params


def test_a_spec_from_rows_equals_the_spec_from_the_file() -> None:
    """The pricing input is bitwise the same whether it came from cents or euros."""
    params = Params.from_dict(LIVE_CONFIG["params"])

    spec, drink_ids = spec_from_rows(_rows_from_live_config(), params)

    assert_specs_equal(spec, spec_from_config(LIVE_CONFIG))
    assert drink_ids == (101, 102, 103, 104, 105, 106)


def test_rows_out_of_slot_order_come_back_in_slot_order() -> None:
    """AC14: position follows `slot`, and each drink keeps its own id and values."""
    rows = _rows_from_live_config()
    shuffled = [rows[i] for i in (3, 0, 5, 1, 4, 2)]

    spec, drink_ids = spec_from_rows(shuffled, Params.from_dict(LIVE_CONFIG["params"]))

    assert drink_ids == (101, 102, 103, 104, 105, 106)
    assert spec.names == tuple(LIVE_CONFIG["names"])
    assert list(spec.p0) == LIVE_CONFIG["p0"]


def test_slots_need_not_be_contiguous() -> None:
    """A removed drink leaves a hole in the slots; the engine's arrays have none."""
    rows = _rows_from_live_config()
    kept = [dataclasses.replace(rows[0], slot=7), dataclasses.replace(rows[4], slot=2)]

    spec, drink_ids = spec_from_rows(kept, Params())

    assert drink_ids == (105, 101)
    assert spec.names == ("Fris", "Bier")


def test_a_removed_row_keeps_its_slot_as_an_inactive_one() -> None:
    """SD15: every row is a slot; `removed` is the mask, not a filter."""
    rows = _rows_from_live_config()
    rows[2] = dataclasses.replace(rows[2], removed=True)

    spec, drink_ids = spec_from_rows(rows, Params.from_dict(LIVE_CONFIG["params"]))

    assert drink_ids == (101, 102, 103, 104, 105, 106)
    assert spec.active.tolist() == [True, True, False, True, True, True]
    assert spec.names == tuple(LIVE_CONFIG["names"])


def test_cents_from_quantised_is_exact_on_every_tenth_up_to_fifty_euros() -> None:
    """SD7: `step_quant` is a multiple of 0.01, so `round(p_q * 100)` is exact."""
    for k in range(501):
        p_q = float(quantize_step(np.float64(k / 10), 0.1))
        assert cents_from_quantised(p_q) == 10 * k, (k, p_q)


def test_cents_from_quantised_on_the_default_half_euro_step() -> None:
    for k in range(101):
        assert cents_from_quantised(float(quantize_step(np.float64(k / 2), 0.5))) == 50 * k


def test_params_survive_a_json_round_trip() -> None:
    params = Params.from_dict({**LIVE_CONFIG["params"], "idle_targets": ["Bier", "Fris"]})

    assert Params.from_dict(params_to_json(params)) == params
    assert params_to_json(params)["idle_targets"] == ["Bier", "Fris"]

"""The engine-state codec: positional arrays to `drink_id`-keyed JSON and back (T6).

AC3 (bit-exact round trip), AC8 (non-finite raises), AC14 (keyed by id); PD7.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from app.db.codec import StateDrinkMismatch, decode_state, encode_state, tick_prices
from exchange import EngineState, PriceJump, advance, initial_state, prices_from_y, schedule_jump
from tests.engine.golden.replay import spec_from_config
from tests.engine.golden.scenarios import LIVE_CONFIG

SPEC = spec_from_config(LIVE_CONFIG)
DRINK_IDS = (11, 12, 13, 14, 15, 16)
SEED = 4242

AWKWARD = (-0.0, 5e-324, 0.1 + 0.2, 1e308, -20.72, 2.6)


def bits(values: object) -> bytes:
    return np.asarray(values, dtype=np.float64).view(np.uint64).tobytes()


def assert_states_identical(left: EngineState, right: EngineState) -> None:
    """`EngineState` is `eq=False`; compare every field, floats by their bits."""
    for key in ("y", "cum_orders", "flow_ema"):
        assert bits(getattr(left, key)) == bits(getattr(right, key)), key
    assert left.last_order_ts.dtype == right.last_order_ts.dtype == np.int64
    assert np.array_equal(left.last_order_ts, right.last_order_ts)
    assert len(left.jumps) == len(right.jumps)
    for a, b in zip(left.jumps, right.jumps, strict=True):
        assert (a.i, a.t0_ms, a.t1_ms) == (b.i, b.t0_ms, b.t1_ms)
        assert bits([a.y0, a.y1]) == bits([b.y0, b.y1])
    for key in ("last_idle_ms", "last_bm_ms", "rng_counter", "version", "tick_index", "t_round"):
        assert getattr(left, key) == getattr(right, key), key


def _awkward_state() -> EngineState:
    """Every float field carries a value `json` or a careless codec would mangle."""
    return EngineState(
        y=np.array(AWKWARD),
        cum_orders=np.array(AWKWARD[::-1]),
        flow_ema=np.array([0.0, -0.0, 1e-300, 7.0, 0.1 + 0.2, -1e308]),
        last_order_ts=np.array([0, -1, 2**53 + 1, 1_700_000_000_000, 5, 6], dtype=np.int64),
        jumps=(
            PriceJump(i=1, y0=-0.0, y1=-20.72, t0_ms=1_000, t1_ms=121_000),
            PriceJump(i=4, y0=5e-324, y1=0.1 + 0.2, t0_ms=-5, t1_ms=2**53 + 1),
        ),
        last_idle_ms=1_700_000_000_123,
        last_bm_ms=-7,
        rng_counter=2**40,
        version=99,
        tick_index=12,
        t_round=3,
    )


def _traded() -> EngineState:
    state = initial_state(SPEC, now_ms=1_000)
    state = schedule_jump(SPEC, state, drink=2, p_target=6.9, duration_ms=60_000, now_ms=1_000)
    for second in range(2, 40, 3):
        orders = np.eye(len(SPEC.names))[second % 6] * 2 if second % 2 else None
        state = advance(SPEC, state, now_ms=second * 1_000, orders=orders, run_seed=SEED).state
    return state


@pytest.mark.parametrize("state", [_awkward_state(), _traded()], ids=["awkward", "traded"])
def test_the_round_trip_is_bit_identical(state: EngineState) -> None:
    """AC3, PD7: `-0.0`, subnormals, `0.1 + 0.2`, `1e308`, saturated `y1` all survive."""
    assert_states_identical(decode_state(encode_state(state, DRINK_IDS), DRINK_IDS), state)


def test_the_stored_json_is_keyed_by_drink_id() -> None:
    """AC14: no array position is persisted."""
    encoded = encode_state(_awkward_state(), DRINK_IDS)

    assert list(json.loads(encoded.y)) == ["11", "12", "13", "14", "15", "16"]
    assert json.loads(encoded.jumps)[0] == {
        "drink_id": 12,
        "y0": -0.0,
        "y1": -20.72,
        "t0_ms": 1_000,
        "t1_ms": 121_000,
    }
    assert '"11": -0.0' in encoded.y


def test_a_decoded_state_advances_exactly_like_the_original() -> None:
    """AC3: across a tick and an order, the decoded state prices identically."""
    original = _traded()
    decoded = decode_state(encode_state(original, DRINK_IDS), DRINK_IDS)
    order = np.array([0, 3, 0, 0, 1, 0])

    results = [
        advance(
            SPEC,
            advance(SPEC, state, now_ms=45_000, run_seed=SEED).state,
            now_ms=46_000,
            orders=order,
            run_seed=SEED,
        ).state
        for state in (original, decoded)
    ]

    assert_states_identical(results[0], results[1])
    assert results[0].version == original.version + 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_raises(value: float) -> None:
    """AC8: `json.dumps(allow_nan=False)`; a NaN is never written."""
    state = _awkward_state()
    poisoned = dataclasses.replace(state, flow_ema=np.array([0, 0, value, 0, 0, 0], dtype=float))

    with pytest.raises(ValueError, match="JSON compliant"):
        encode_state(poisoned, DRINK_IDS)


def test_a_non_finite_jump_value_raises() -> None:
    state = _awkward_state()
    poisoned = dataclasses.replace(
        state, jumps=(PriceJump(i=0, y0=0.0, y1=float("nan"), t0_ms=0, t1_ms=1),)
    )

    with pytest.raises(ValueError, match="JSON compliant"):
        encode_state(poisoned, DRINK_IDS)


def test_decoding_in_a_new_order_gives_each_drink_its_own_values() -> None:
    """AC14: encoded with drink ids (7, 3), decoded with (3, 7)."""
    state = EngineState(
        y=np.array([1.5, -2.5]),
        cum_orders=np.array([10.0, 20.0]),
        flow_ema=np.array([0.1, 0.2]),
        last_order_ts=np.array([700, 300], dtype=np.int64),
        jumps=(PriceJump(i=0, y0=1.5, y1=3.0, t0_ms=0, t1_ms=10),),
        last_idle_ms=0,
        last_bm_ms=0,
        rng_counter=0,
        version=1,
        tick_index=0,
        t_round=0,
    )

    decoded = decode_state(encode_state(state, (7, 3)), (3, 7))

    assert list(decoded.y) == [-2.5, 1.5]
    assert list(decoded.cum_orders) == [20.0, 10.0]
    assert list(decoded.flow_ema) == [0.2, 0.1]
    assert list(decoded.last_order_ts) == [300, 700]
    assert decoded.jumps == (PriceJump(i=1, y0=1.5, y1=3.0, t0_ms=0, t1_ms=10),)


@pytest.mark.parametrize(
    ("decode_ids", "named"),
    [
        ((11, 12, 13, 14, 15), "extra: 16"),
        ((11, 12, 13, 14, 15, 16, 17), "missing: 17"),
        ((11, 12, 13, 14, 15, 99), "missing: 99; extra: 16"),
    ],
)
def test_a_drink_set_mismatch_raises_and_names_the_ids(
    decode_ids: tuple[int, ...], named: str
) -> None:
    encoded = encode_state(_awkward_state(), DRINK_IDS)

    with pytest.raises(StateDrinkMismatch, match=named) as raised:
        decode_state(encoded, decode_ids)
    assert raised.value.status_code == 500


def test_a_jump_on_an_unknown_drink_raises_and_names_it() -> None:
    encoded = encode_state(_awkward_state(), DRINK_IDS)
    jumps = json.loads(encoded.jumps)
    jumps[1]["drink_id"] = 77
    orphaned = dataclasses.replace(encoded, jumps=json.dumps(jumps))

    with pytest.raises(StateDrinkMismatch, match="77"):
        decode_state(orphaned, DRINK_IDS)


def test_tick_prices_are_keyed_by_drink_id() -> None:
    """SD10: `{drink_id: {"p_cont", "p_q"}}` from `prices_from_y`."""
    state = _traded()
    p_cont, p_q = prices_from_y(state.y, SPEC.p_min, SPEC.p_max, SPEC.params.step_quant)

    prices = tick_prices(SPEC, state, DRINK_IDS)

    assert list(prices) == list(DRINK_IDS)
    for i, drink_id in enumerate(DRINK_IDS):
        assert prices[drink_id] == {"p_cont": float(p_cont[i]), "p_q": float(p_q[i])}
        assert type(prices[drink_id]["p_q"]) is float

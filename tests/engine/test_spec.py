"""`exchange.spec`: frozen `Params` and `MarketSpec`, AC5, D-21 (Phase 1 plan T2)."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import numpy as np
import pytest

from exchange.spec import DrinkSpec, MarketSpec, Params, anchor_s0_to_current_y
from tests.engine.golden.scenarios import DEFAULT_CONFIG, LIVE_CONFIG
from tests.engine.v1_reference import engine as v1

ARRAYS = ("p_min", "p_max", "p0", "a", "d", "s0", "c")


def _spec_from_v1_config(config: dict[str, Any]) -> MarketSpec:
    """What v1's `from_persist` builds (engine.py:153-164), as a `MarketSpec`."""
    st = v1.ExchangeState.from_persist(copy.deepcopy(config))
    return MarketSpec(
        names=tuple(st.names),
        **{k: getattr(st, k) for k in ARRAYS},
        params=Params.from_dict(config.get("params", {})),
    )


def _drinks(**overrides: float) -> list[DrinkSpec]:
    base = {"p_min": 1.0, "p_max": 4.0, "p0": 2.0, "a": 0.0, "d": 0.0, "s0": 0.0, "c": 0.0}
    return [
        DrinkSpec(name="Bier", **{**base, **overrides}),
        DrinkSpec(name="Fris", **base),
    ]


# --- Params -------------------------------------------------------------------


def _as_v1_dict(params: Params) -> dict[str, Any]:
    d = dataclasses.asdict(params)
    return {k: list(v) if isinstance(v, tuple) else v for k, v in d.items()}


def test_params_has_every_v1_field_with_v1_defaults() -> None:
    assert _as_v1_dict(Params()) == v1.Params().to_dict()


@pytest.mark.parametrize("config", [LIVE_CONFIG, DEFAULT_CONFIG], ids=["live", "default"])
def test_params_from_dict_reads_a_v1_config_as_v1_does(config: dict[str, Any]) -> None:
    raw = copy.deepcopy(config.get("params", {}))
    assert _as_v1_dict(Params.from_dict(raw)) == v1.Params.from_dict(raw).to_dict()


def test_params_from_dict_rejects_an_unknown_key() -> None:
    with pytest.raises(ValueError, match="bm_sigmaa"):
        Params.from_dict({"bm_sigmaa": 0.2})


def test_params_is_frozen_and_its_target_lists_are_tuples() -> None:
    params = Params.from_dict({"idle_targets": ["Bier"], "idle_rise_targets": ["Fris"]})
    assert params.idle_targets == ("Bier",)
    assert params.idle_rise_targets == ("Fris",)
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.eta = 1.0  # type: ignore[misc]


# --- MarketSpec: the configs in this repo -------------------------------------


@pytest.mark.parametrize("config", [LIVE_CONFIG, DEFAULT_CONFIG], ids=["live", "default"])
def test_the_v1_configs_construct_cleanly(config: dict[str, Any]) -> None:
    spec = _spec_from_v1_config(config)
    st = v1.ExchangeState.from_persist(copy.deepcopy(config))
    assert spec.names == tuple(st.names)
    for key in ARRAYS:
        assert np.array_equal(getattr(spec, key), getattr(st, key)), key
        assert getattr(spec, key).dtype == np.float64


def test_every_array_is_read_only() -> None:
    spec = _spec_from_v1_config(LIVE_CONFIG)
    for key in ARRAYS:
        with pytest.raises(ValueError, match="read-only"):
            getattr(spec, key)[0] = 0.0


def test_the_spec_does_not_alias_its_inputs() -> None:
    p_min = np.array([1.0, 1.0])
    spec = MarketSpec(
        names=("Bier", "Fris"),
        p_min=p_min,
        p_max=np.array([4.0, 4.0]),
        p0=np.array([2.0, 2.0]),
        a=np.zeros(2),
        d=np.zeros(2),
        s0=np.zeros(2),
        c=np.zeros(2),
        params=Params(),
    )
    p_min[0] = 1.9
    assert spec.p_min[0] == 1.0


def test_from_drinks_builds_the_arrays_in_drink_order() -> None:
    spec = MarketSpec.from_drinks(_drinks(p_min=0.5), Params())
    assert spec.names == ("Bier", "Fris")
    assert np.array_equal(spec.p_min, [0.5, 1.0])


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError, match="length"):
        MarketSpec(
            names=("Bier", "Fris"),
            p_min=np.array([1.0]),
            p_max=np.array([4.0, 4.0]),
            p0=np.array([2.0, 2.0]),
            a=np.zeros(2),
            d=np.zeros(2),
            s0=np.zeros(2),
            c=np.zeros(2),
            params=Params(),
        )


# --- AC5 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"p0": 1.0}, id="p_min-equals-p0"),
        pytest.param({"p0": 0.5}, id="p_min-above-p0"),
        pytest.param({"p0": 4.0}, id="p0-equals-p_max"),
        pytest.param({"p0": 4.5}, id="p0-above-p_max"),
        pytest.param({"p0": float("nan")}, id="p0-nan"),
    ],
)
def test_ac5_bounds_out_of_order_raise_naming_the_drink(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="Bier"):
        MarketSpec.from_drinks(_drinks(**overrides), Params())


@pytest.mark.parametrize("step", [0.0, -0.1, float("nan"), float("inf")])
def test_ac5_a_non_positive_step_quant_raises(step: float) -> None:
    with pytest.raises(ValueError, match="step_quant"):
        MarketSpec.from_drinks(_drinks(), Params(step_quant=step))


@pytest.mark.parametrize("step", [0.015, 0.001, 0.333, 0.1 + 1e-6])
def test_ac5_a_step_quant_off_the_cent_grid_raises(step: float) -> None:
    with pytest.raises(ValueError, match=r"multiple of 0\.01"):
        MarketSpec.from_drinks(_drinks(), Params(step_quant=step))


@pytest.mark.parametrize("step", [0.01, 0.05, 0.07, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5])
def test_ac5_a_step_quant_on_the_cent_grid_passes(step: float) -> None:
    """0.1 and 0.5 must pass even though 0.1 / 0.01 == 10.000000000000002."""
    MarketSpec.from_drinks(_drinks(), Params(step_quant=step))


# --- D-21: anchor_s0_to_current_y ----------------------------------------------


@pytest.mark.parametrize("config", [LIVE_CONFIG, DEFAULT_CONFIG], ids=["live", "default"])
def test_anchor_s0_to_current_y_matches_v1_calibrate(config: dict[str, Any]) -> None:
    rng = np.random.default_rng(21)
    spec = _spec_from_v1_config(config)
    st = v1.ExchangeState.from_persist(copy.deepcopy(config))
    for _ in range(1000):
        y = rng.uniform(-7.0, 7.0, len(spec.names))
        a, d, c = (rng.uniform(-3.0, 12.0, len(spec.names)) for _ in range(3))
        st.y, st.a, st.d, st.c = y.copy(), a.copy(), d.copy(), c.copy()
        v1.calibrate_s0_to_p0(st)
        anchored = anchor_s0_to_current_y(dataclasses.replace(spec, a=a, d=d, c=c), y)
        assert np.array_equal(anchored.s0, st.s0)


def test_anchoring_returns_a_new_spec_and_leaves_the_old_one_alone() -> None:
    spec = _spec_from_v1_config(DEFAULT_CONFIG)
    before = spec.s0.copy()
    anchored = anchor_s0_to_current_y(spec, np.full(len(spec.names), 1.5))
    assert anchored is not spec
    assert np.array_equal(spec.s0, before)
    assert not np.array_equal(anchored.s0, before)

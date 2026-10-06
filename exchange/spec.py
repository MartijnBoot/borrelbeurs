"""What a market is: per-drink bounds and coefficients, plus the tuning `Params`.

Both types are frozen, and every array a `MarketSpec` holds is a read-only
float64 copy of what it was given (plan D14), so a step that tried to mutate
the spec would raise rather than pass silently.

`MarketSpec.active` is the one exception to float64: a read-only bool mask,
all true unless a drink was removed from a live run (Phase 6 SD14). An
inactive slot keeps its place in every array, takes no part in any mean or
sum, and its per-slot state is frozen.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from exchange.pricing import FloatArray, prices_from_y

BoolArray = NDArray[np.bool_]

_ARRAYS = ("p_min", "p_max", "p0", "a", "d", "s0", "c")


@dataclass(frozen=True)
class Params:
    """Every v1 tuning parameter, with v1's defaults (v1 engine.py:45-69)."""

    alpha_price: float = 0.0
    lambda_orders: float = 0.8
    eta: float = 0.6
    K: float = 12.0
    step_quant: float = 0.5
    phi_persist: float = 0.03
    decay_rho: float = 0.98
    history_window_minutes: float = 15.0
    refresh_minutes: float = 1.0
    idle_decay_minutes: float = 1.0
    idle_strength: float = 0.5
    idle_targets: tuple[str, ...] = field(default_factory=tuple)
    idle_rise_minutes: float = 1.0
    idle_rise_strength: float = 0.5
    idle_rise_targets: tuple[str, ...] = field(default_factory=tuple)
    bm_enabled: bool = True
    bm_sigma: float = 0.15  # legacy; v1's config endpoint maps it onto bm_sigma_y
    bm_dt_minutes: float = 1.0
    bm_sigma_y: float = 0.18  # volatility in y per sqrt(minute)
    flow_vol_amp: float = 0.7
    flow_beta: float = 0.25
    y_clip: float = 6.0
    auto_calibrate_s0: bool = False
    demand_enabled: bool = True

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Params:
        """Read a v1 `params` dict. Unlike v1, an unknown key is an error, not ignored."""
        known = {f.name: f for f in dataclasses.fields(cls)}
        unknown = sorted(set(d) - set(known))
        if unknown:
            raise ValueError(f"unknown Params field(s): {', '.join(unknown)}")
        values: dict[str, Any] = {}
        for key, value in d.items():
            kind = known[key].type
            if kind == "bool":
                values[key] = bool(value)
            elif kind == "tuple[str, ...]":
                values[key] = tuple(str(v) for v in value)
            else:
                values[key] = float(value)
        return cls(**values)


@dataclass(frozen=True)
class DrinkSpec:
    name: str
    p_min: float
    p_max: float
    p0: float
    a: float
    d: float
    s0: float
    c: float
    active: bool = True


@dataclass(frozen=True, eq=False)
class MarketSpec:
    """The market's static description, one array slot per drink.

    Raises `ValueError` at construction unless, for every drink,
    `p_min < p0 < p_max`, and `step_quant` is a positive multiple of 0.01 (AC5),
    and at least one drink is active.

    `active` defaults to every slot active; `None` is only that default.
    """

    names: tuple[str, ...]
    p_min: FloatArray
    p_max: FloatArray
    p0: FloatArray
    a: FloatArray
    d: FloatArray
    s0: FloatArray
    c: FloatArray
    params: Params
    active: BoolArray = None  # type: ignore[assignment]  # None: every slot active

    def __post_init__(self) -> None:
        n = len(self.names)
        for key in _ARRAYS:
            arr = np.array(getattr(self, key), dtype=np.float64)
            if arr.shape != (n,):
                raise ValueError(f"{key} has length {arr.shape}, expected ({n},) for {n} drinks")
            arr.setflags(write=False)
            object.__setattr__(self, key, arr)
        active = np.ones(n, dtype=bool) if self.active is None else np.array(self.active, bool)
        if active.shape != (n,):
            raise ValueError(f"active has length {active.shape}, expected ({n},) for {n} drinks")
        if not active.any():
            raise ValueError("a market needs at least one active drink")
        active.setflags(write=False)
        object.__setattr__(self, "active", active)
        for i, name in enumerate(self.names):
            lo, p0, hi = self.p_min[i], self.p0[i], self.p_max[i]
            if not (lo < p0 < hi):
                raise ValueError(f"{name}: need p_min < p0 < p_max, got {lo} / {p0} / {hi}")
        _check_step_quant(self.params.step_quant)

    @classmethod
    def from_drinks(cls, drinks: Iterable[DrinkSpec], params: Params) -> MarketSpec:
        drinks = list(drinks)
        return cls(
            names=tuple(dr.name for dr in drinks),
            **{key: np.array([getattr(dr, key) for dr in drinks]) for key in _ARRAYS},
            params=params,
            active=np.array([dr.active for dr in drinks], dtype=bool),
        )


def _check_step_quant(step: float) -> None:
    if not (math.isfinite(step) and step > 0):
        raise ValueError(f"step_quant must be positive and finite, got {step}")
    # 0.1 * 100 == 10.000000000000002: compare to the nearest whole number of cents.
    cents = step * 100
    if abs(cents - round(cents)) > 1e-9 * max(1.0, cents):
        raise ValueError(f"step_quant must be a multiple of 0.01, got {step}")


def anchor_s0_to_current_y(spec: MarketSpec, y: FloatArray) -> MarketSpec:
    """A new spec whose `s0` makes expected flow balance at the *current* prices.

    This is v1's `calibrate_s0_to_p0` (v1 engine.py:38-41), renamed because the
    old name lies (D-21): it never looked at `p0`. It quantises the prices `y`
    gives now and solves for the `s0` at which the demand model is flat there.

    The mean is over active drinks only, and an inactive drink's `s0` is kept
    (SD14).
    """
    _, p_q = prices_from_y(y, spec.p_min, spec.p_max, spec.params.step_quant)
    p_mean0 = float(np.mean(p_q[spec.active]))
    s0 = spec.d * p_q - spec.a - spec.c * (p_mean0 - p_q)
    return dataclasses.replace(spec, s0=np.where(spec.active, s0, spec.s0))

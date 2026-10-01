"""The six golden scenarios, as plain data (Phase 1 plan T1, D3, D10, D11).

A scenario is a config, a `run_seed`, a start instant and an ordered list of
events. Four event kinds exist, each standing for one exact v1 API call
sequence (plan D3; `capture.py` is the code that spells them out):

- `{"kind": "tick", "t": ms}` -- one broadcast payload: idle, jumps, Brownian.
- `{"kind": "order", "t": ms, "vec": [qty, ...]}` -- `POST /order` with the
  name->vector mapping already done (plan D12: that mapping stays outside the
  engine).
- `{"kind": "jump", "t": ms, "drink": i, "target": price, "duration_ms": ms}`
  -- `POST /price-jump`.
- `{"kind": "crash", "t": ms, "target": "min"|"max"|"mid", "duration_ms": ms}`
  -- `POST /market-crash`.

Ticks fall on a 1 Hz grid from `start_ms`; orders and admin actions land at
scripted milliseconds strictly between two ticks (D11). The order scripts come
from a fixed `random.Random(seed)`, and the generated events are written into
each fixture, so a replay reads them back rather than regenerating them.

`requires` names the branch a scenario exists to exercise. `capture.py` fails
when a scenario no longer reaches it -- a scenario that silently stops
exercising its branch is a guard that cannot fail.
"""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

Event = dict[str, Any]

# What runs in production (spec: "Scenario 1 is first deliberately").
LIVE_CONFIG: dict[str, Any] = json.loads(
    (REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json").read_text(encoding="utf-8")
)
# An empty document: `ExchangeState.from_persist` fills in v1's own defaults
# (engine.py:154-163), which include `demand_enabled: true`.
DEFAULT_CONFIG: dict[str, Any] = {}

START_MS = 1_759_312_800_000  # 2025-10-01T10:00:00Z; any fixed instant would do
SECOND = 1_000
MINUTE = 60 * SECOND

# Live-config drink indices, by v1 name (exchange_config.json "names").
BIER, WIJN, STELZ, SHOT, FRIS, VODKA = range(6)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    config: dict[str, Any]
    run_seed: int
    start_ms: int
    events: tuple[Event, ...]
    requires: frozenset[str] = field(default_factory=frozenset)


OrderFn = Callable[[random.Random, int], list[float] | None]


def _timeline(
    rng: random.Random,
    seconds: int,
    order_at: OrderFn,
    admin: dict[int, Event] | None = None,
) -> tuple[Event, ...]:
    """One tick per second; per second at most one order and one admin action.

    `order_at(rng, k)` returns the order vector placed during second `k`, or
    None. `admin[k]` is a jump/crash event placed during second `k` (its `t` is
    filled in here). Offsets keep every event strictly between two ticks, the
    admin action before the order.
    """
    events: list[Event] = []
    for k in range(seconds):
        base = START_MS + k * SECOND
        events.append({"kind": "tick", "t": base})
        if admin and k in admin:
            events.append({**admin[k], "t": base + 250})
        vec = order_at(rng, k)
        if vec is not None:
            events.append({"kind": "order", "t": base + rng.randint(300, 999), "vec": vec})
    return tuple(events)


def _random_order(
    rng: random.Random, weights: list[float], max_qty: int, n_drinks: int = 6
) -> list[float]:
    """A batch of one to three lines, drinks drawn by popularity."""
    vec = [0.0] * n_drinks
    for _ in range(rng.randint(1, 3)):
        i = rng.choices(range(n_drinks), weights=weights)[0]
        vec[i] += float(rng.randint(1, max_qty))
    return vec


def _only(drink: int, qty: float, n_drinks: int = 6) -> list[float]:
    vec = [0.0] * n_drinks
    vec[drink] = qty
    return vec


# Bier sells most, the expensive Vodka Red Bull least: a plausible borrel.
LIVE_WEIGHTS = [6.0, 2.0, 1.0, 3.0, 2.5, 0.8]


def _s1_live() -> Scenario:
    rng = random.Random(101)

    def order_at(r: random.Random, k: int) -> list[float] | None:
        return _random_order(r, LIVE_WEIGHTS, 4) if r.random() < 0.35 else None

    return Scenario(
        name="s1_live",
        description="Live config, 30 min of scripted orders.",
        config=copy.deepcopy(LIVE_CONFIG),
        run_seed=20261001,
        start_ms=START_MS,
        events=_timeline(rng, 30 * 60, order_at),
    )


def _s2_jump() -> Scenario:
    rng = random.Random(202)
    jump_at = 90  # active 90.25 s .. 150.25 s; Brownian fires at the 120 s tick

    def order_at(r: random.Random, k: int) -> list[float] | None:
        if jump_at <= k < jump_at + 60:
            # The jumping drink keeps selling, hard, for the whole jump.
            vec = _only(STELZ, float(r.randint(2, 5)))
            if r.random() < 0.3:
                vec[BIER] += 1.0
            return vec
        return _random_order(r, LIVE_WEIGHTS, 3) if r.random() < 0.3 else None

    jump = {"kind": "jump", "drink": STELZ, "target": 4.0, "duration_ms": 60 * SECOND}
    return Scenario(
        name="s2_jump",
        description="Live config, a 60 s price jump on Stelz with Stelz orders throughout it.",
        config=copy.deepcopy(LIVE_CONFIG),
        run_seed=20261002,
        start_ms=START_MS,
        events=_timeline(rng, 4 * 60, order_at, {jump_at: jump}),
        requires=frozenset({"bm_during_jump"}),
    )


def _s3_bounds() -> Scenario:
    rng = random.Random(303)
    reverse_at = 4 * 60

    def order_at(r: random.Random, k: int) -> list[float] | None:
        # First Wijn alone: it climbs to p_max and every other drink, Fris
        # included, sinks to p_min. Then Fris alone: Fris is ordered while
        # pinned at p_min, and Wijn feels negative pressure while pinned at
        # p_max once its persistent cum_orders has decayed.
        if k < reverse_at:
            return _only(WIJN, float(r.randint(4, 6)))
        return _only(FRIS, float(r.randint(4, 6)))

    return Scenario(
        name="s3_bounds",
        description="Live config, Wijn driven to p_max and Fris to p_min, then reversed.",
        config=copy.deepcopy(LIVE_CONFIG),
        run_seed=20261003,
        start_ms=START_MS,
        events=_timeline(rng, 8 * 60, order_at),
        requires=frozenset({"unstick_up", "unstick_down"}),
    )


def _s4_default() -> Scenario:
    rng = random.Random(404)

    def order_at(r: random.Random, k: int) -> list[float] | None:
        if r.random() >= 0.5:
            return None
        # Volumes around v1's default expected flow (~17 per drink), so the
        # demand term pushes both ways.
        return [float(r.randint(0, 30)) if r.random() < 0.6 else 0.0 for _ in range(6)]

    return Scenario(
        name="s4_default",
        description="v1 default config (demand_enabled: true), 10 min of orders.",
        config=copy.deepcopy(DEFAULT_CONFIG),
        run_seed=20261004,
        start_ms=START_MS,
        events=_timeline(rng, 10 * 60, order_at),
        requires=frozenset({"expected_flow_nonzero"}),
    )


def _s5_crash() -> Scenario:
    rng = random.Random(505)
    crash_at = 120  # active 120.25 s .. 150.25 s; then 5.5 min of trading

    def order_at(r: random.Random, k: int) -> list[float] | None:
        return _random_order(r, LIVE_WEIGHTS, 4) if r.random() < 0.4 else None

    crash = {"kind": "crash", "target": "min", "duration_ms": 30 * SECOND}
    return Scenario(
        name="s5_crash",
        description='Live config, orders, crash("min", 30 s), then 5.5 min of ticks and orders.',
        config=copy.deepcopy(LIVE_CONFIG),
        run_seed=20261005,
        start_ms=START_MS,
        events=_timeline(rng, 8 * 60, order_at, {crash_at: crash}),
        requires=frozenset({"crash_end_all_p_min"}),
    )


def _s6_idle() -> Scenario:
    rng = random.Random(606)
    config = copy.deepcopy(LIVE_CONFIG)
    config["params"]["idle_targets"] = ["Stelz"]
    config["params"]["idle_rise_targets"] = ["Fris"]
    # Stelz and Fris are ordered rarely, so both go idle and come back.
    weights = [6.0, 2.0, 0.15, 3.0, 0.15, 0.8]

    def order_at(r: random.Random, k: int) -> list[float] | None:
        return _random_order(r, weights, 3) if r.random() < 0.35 else None

    return Scenario(
        name="s6_idle",
        description="Live config with idle decay on Stelz and idle rise on Fris, 6 min.",
        config=config,
        run_seed=20261006,
        start_ms=START_MS,
        events=_timeline(rng, 6 * 60, order_at),
        requires=frozenset({"idle_decay", "idle_rise"}),
    )


SCENARIOS: tuple[Scenario, ...] = (
    _s1_live(),
    _s2_jump(),
    _s3_bounds(),
    _s4_default(),
    _s5_crash(),
    _s6_idle(),
)


def by_name(name: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(name)

"""Property tests: determinism (AC3) and a differential fuzz against v1 (Phase 1 plan T9).

(a) AC3 -- replaying the same random sequence twice gives identical states at
    every step.
(b) Differential -- random configs and event sequences, driven through the v1
    reference (`capture.run_v1`) and the pure engine (`replay.replay`), give
    identical records at every step: AC1 beyond the six scenarios, including
    the branches the live config never takes (`alpha_price != 0`, the demand
    model, idle targets, `auto_calibrate_s0`).

Seeds are fixed and every failure names its seed and event index. A
differential failure is a hard stop even in a dead-code branch (plan T9).
Generators use the standard library's `random.Random`, which is banned only
inside `exchange/`.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from exchange import EngineState
from tests.engine.golden import capture, replay
from tests.engine.golden.scenarios import Event

START_MS = 1_759_312_800_000
N_DETERMINISM = 2000
N_DIFFERENTIAL = 500
STEPS = (0.01, 0.05, 0.1, 0.2, 0.25, 0.5)


def random_config(r: random.Random) -> dict[str, Any]:
    """A v1-shaped config inside AC5's bounds, exercising every branch."""
    n = r.randint(2, 7)
    names = [f"drink{i}" for i in range(n)]
    p_min = [round(r.uniform(0.5, 8.0), 2) for _ in range(n)]
    p_max = [lo + round(r.uniform(1.0, 6.0), 2) for lo in p_min]
    p0 = [lo + (hi - lo) * r.uniform(0.05, 0.95) for lo, hi in zip(p_min, p_max, strict=True)]

    def coeff(lo: float, hi: float) -> list[float]:
        return [r.uniform(lo, hi) for _ in range(n)] if r.random() < 0.6 else [0.0] * n

    def targets() -> list[str]:
        return [nm for nm in names if r.random() < 0.3] + (["ghost"] if r.random() < 0.05 else [])

    def num(lo: float, hi: float) -> float | int:
        value = r.uniform(lo, hi)
        return round(value) if r.random() < 0.1 else value  # v1 configs may hold ints

    params: dict[str, Any] = {
        "alpha_price": r.uniform(-1.0, 1.0) if r.random() < 0.4 else 0.0,
        "lambda_orders": num(0.0, 2.0),
        "eta": num(0.1, 1.5),
        "K": num(1.0, 15.0),
        "step_quant": r.choice(STEPS),
        "phi_persist": r.uniform(0.0, 0.3),
        "decay_rho": r.uniform(0.8, 1.0),
        "refresh_minutes": r.choice([0.05, 0.2, 1.0]),
        "idle_decay_minutes": r.choice([0.0, 0.1, 1.0]),
        "idle_strength": r.uniform(-2.0, 2.0),
        "idle_targets": targets(),
        "idle_rise_minutes": r.choice([0.0, 0.1, 1.0]),
        "idle_rise_strength": r.uniform(-2.0, 2.0),
        "idle_rise_targets": targets(),
        "bm_enabled": r.random() < 0.85,
        "bm_dt_minutes": r.choice([0.1, 0.5, 1.0]),
        "bm_sigma_y": r.choice([0.0, 0.18, 0.4]),
        "flow_vol_amp": r.uniform(0.0, 1.5),
        "flow_beta": r.uniform(0.0, 1.0),
        "y_clip": r.choice([3.0, 6.0]),
        "auto_calibrate_s0": r.random() < 0.3,
        "demand_enabled": r.random() < 0.5,
    }
    return {
        "names": names,
        "p_min": p_min,
        "p_max": p_max,
        "p0": p0,
        "a": coeff(0.0, 12.0),
        "d": coeff(0.0, 1.5),
        "s0": coeff(-5.0, 10.0),
        "c": coeff(0.0, 1.0),
        "params": params,
    }


def random_events(r: random.Random, config: dict[str, Any], count: int) -> list[Event]:
    n = len(config["names"])
    t = START_MS
    events: list[Event] = []
    for _ in range(count):
        t += r.choice([0, 1, 250, 1_000, 1_000, 5_000, 30_000, 70_000])
        roll = r.random()
        if roll < 0.45:
            events.append({"kind": "tick", "t": t})
        elif roll < 0.9:
            vec = [float(r.randint(0, 6)) if r.random() < 0.5 else 0.0 for _ in range(n)]
            events.append({"kind": "order", "t": t, "vec": vec})
        elif roll < 0.97:
            i = r.randrange(n)
            lo, hi = config["p_min"][i], config["p_max"][i]
            events.append(
                {
                    "kind": "jump",
                    "t": t,
                    "drink": i,
                    "target": r.uniform(lo - 2.0, hi + 2.0),
                    "duration_ms": r.choice([0, 1, 2_000, 20_000, 60_000]),
                }
            )
        else:
            events.append(
                {
                    "kind": "crash",
                    "t": t,
                    "target": r.choice(["min", "max", "mid"]),
                    "duration_ms": r.choice([1, 10_000, 30_000]),
                }
            )
    return events


def _state_key(state: EngineState) -> tuple[Any, ...]:
    return (
        state.y.tobytes(),
        state.cum_orders.tobytes(),
        state.flow_ema.tobytes(),
        state.last_order_ts.tobytes(),
        state.jumps,
        state.last_idle_ms,
        state.last_bm_ms,
        state.rng_counter,
        state.version,
        state.tick_index,
        state.t_round,
    )


def _trajectory(config: dict[str, Any], seed: int, events: list[Event]) -> list[tuple[Any, ...]]:
    spec, state = replay.start(config, START_MS)
    keys = []
    for event in events:
        state = replay.step(spec, state, event, seed)
        keys.append(_state_key(state))
    return keys


def test_ac3_advance_is_deterministic_over_random_sequences() -> None:
    r = random.Random(3_000)
    moved = 0
    for case in range(N_DETERMINISM):
        seed = r.randrange(2**32)
        config = random_config(r)
        events = random_events(r, config, r.randint(1, 15))
        first = _trajectory(config, seed, events)
        second = _trajectory(config, seed, events)
        for k, (a, b) in enumerate(zip(first, second, strict=True)):
            assert a == b, f"case {case}, run_seed {seed}: nondeterministic at event {k}"
        _, initial = replay.start(config, START_MS)
        moved += int(first[-1][0] != initial.y.tobytes())
    assert moved > N_DETERMINISM // 2, "the sequences must actually move prices"


def test_a_different_run_seed_gives_a_different_noise_stream() -> None:
    r = random.Random(3_001)
    config = random_config(r)
    config["params"].update(bm_enabled=True, bm_sigma_y=0.18)
    events: list[Event] = [{"kind": "tick", "t": START_MS + 60_000 * k} for k in range(5)]
    assert _trajectory(config, 1, events) != _trajectory(config, 2, events)


def test_differential_the_engine_matches_v1_on_random_sequences() -> None:
    r = random.Random(4_000)
    branches = {"alpha": 0, "demand_on": 0, "demand_off": 0, "idle": 0, "calibrate": 0}
    for case in range(N_DIFFERENTIAL):
        seed = r.randrange(2**32)
        config = random_config(r)
        events = random_events(r, config, r.randint(5, 40))
        want, _ = capture.run_v1(config, seed, START_MS, events)
        got = replay.replay(config, seed, START_MS, events)
        for k, (w, g) in enumerate(zip(want, got, strict=True)):
            diff = capture.first_difference(w, g)
            assert diff is None, f"case {case}, run_seed {seed}: event {k} differs at {diff}"
        p = config["params"]
        branches["alpha"] += int(p["alpha_price"] != 0)
        branches["demand_on" if p["demand_enabled"] else "demand_off"] += 1
        branches["idle"] += int(bool(p["idle_targets"] or p["idle_rise_targets"]))
        branches["calibrate"] += int(p["auto_calibrate_s0"])
    assert all(count >= 50 for count in branches.values()), branches


def test_the_differential_compares_something() -> None:
    """Anti-vacuity: a perturbed replay record is caught by the same comparison."""
    r = random.Random(4_001)
    config = random_config(r)
    events = random_events(r, config, 10)
    want, _ = capture.run_v1(config, 7, START_MS, events)
    got = replay.replay(config, 7, START_MS, events)
    got[-1]["p_q"][0] = float(np.nextafter(got[-1]["p_q"][0], np.inf))
    assert capture.first_difference(want[-1], got[-1]) == "p_q[0]"

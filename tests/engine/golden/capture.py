"""Drive the v1 reference engine through a scenario and record its prices.

    uv run python -m tests.engine.golden.capture --write   # (re)write the fixtures
    uv run python -m tests.engine.golden.capture --check   # recapture, diff, exit 1 on change

**The clock.** v1 reads time through its module-level `now_ms()` and nothing
else, so replacing that one attribute for the duration of a run makes the whole
engine run on scenario time. It is restored afterwards.

**The noise (plan D1).** v1 draws Brownian noise from `self.rng.normal(...)`.
After `init`, that attribute is replaced by `CounterRng`, whose k-th call returns
`default_rng(SeedSequence([run_seed, k])).normal(loc, scale, size)` -- the
derivation the pure engine uses with `k = rng_counter`. Nothing else in v1's
maths changes; only where its noise comes from.

**The call sequences (plan D3)** are v1's API code with everything that never
touches `y` left in, so the reference runs exactly as production did:

- tick  = `_snapshot_payload_unlocked` (legacy/v1/backend/api.py:775-778):
  idle, jumps, Brownian, `snapshot_if_due`.
- order = `post_order` (api.py:355-392): `flow_ema`, `last_order_ts`,
  `single_step`, `t_round + 1`, totals, jumps, trim history -- then the tick
  sequence, via `_save_snapshot`. Jumps therefore run twice (plan R10).
- jump  = `price_jump` (api.py:469-472): schedule, then the tick sequence.
- crash = `market_crash` (api.py:482-509): schedule every drink, then the tick
  sequence.

**Branch hits.** While driving, the capture notes which branches were reached
(see `_HITS`); a scenario whose `requires` is not a subset raises `BranchNotHit`.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from tests.engine.golden.scenarios import SCENARIOS, Event, Scenario
from tests.engine.v1_reference import engine as v1

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_TOL = 1e-9  # v1's own bound-equality tolerance (engine.py:214)

_HITS = {
    "bm": "a Brownian step drew noise",
    "bm_during_jump": "a Brownian step drew noise while a price jump was still active",
    "unstick_up": "single_step's p_min unstick branch replaced y (engine.py:216-220)",
    "unstick_down": "single_step's p_max unstick branch replaced y (engine.py:221-225)",
    "expected_flow_nonzero": "an order step saw non-zero expected flow",
    "crash_end_all_p_min": "every drink was quoted at p_min once a crash to min ended",
    "idle_decay": "an idle step pushed an idle_targets drink down",
    "idle_rise": "an idle step pushed an idle_rise_targets drink up",
}


class BranchNotHit(AssertionError):
    pass


class CounterRng:
    """Stands in for v1's `engine.rng`: one fresh, counter-seeded draw per call (D1)."""

    def __init__(self, run_seed: int) -> None:
        self.run_seed = run_seed
        self.counter = 0

    def normal(self, loc: float, scale: Any, size: int) -> NDArray[np.float64]:
        rng = np.random.default_rng(np.random.SeedSequence([self.run_seed, self.counter]))
        self.counter += 1
        draw: NDArray[np.float64] = rng.normal(loc, scale, size)
        return draw


@contextmanager
def _clock(start_ms: int) -> Iterator[list[int]]:
    """Point v1's `now_ms` at a mutable cell; restore the real clock on exit."""
    now = [start_ms]
    original = v1.now_ms
    v1.now_ms = lambda: now[0]
    try:
        yield now
    finally:
        v1.now_ms = original


class _Driver:
    def __init__(self, config: dict[str, Any], run_seed: int, now: list[int]) -> None:
        self.now = now
        self.st = v1.ExchangeState.from_persist(copy.deepcopy(config))
        self.rng = CounterRng(run_seed)
        self.st.rng = self.rng
        self.hits: set[str] = set()
        self._crash_ends: list[tuple[int, str]] = []

    # --- v1 API call sequences (D3) ---------------------------------------

    def tick(self) -> None:
        st = self.st
        self._idle()
        st.apply_price_jumps_if_needed()
        jump_active = bool(st.price_jumps)
        drawn = self.rng.counter
        st.apply_bm_if_needed()
        if self.rng.counter > drawn:
            self.hits.add("bm")
            if jump_active:
                self.hits.add("bm_during_jump")
        st.snapshot_if_due()

    def order(self, vec: NDArray[np.float64]) -> None:
        st = self.st
        st.flow_ema = (1.0 - st.params.flow_beta) * st.flow_ema + st.params.flow_beta * vec
        nowts = v1.now_ms()
        for i, q in enumerate(vec):
            if q > 0:
                st.last_order_ts[i] = nowts
        self._single_step(vec)
        st.t_round += 1
        st.totals_ordered += vec
        st.apply_price_jumps_if_needed()
        st._trim_history()
        self.tick()

    def jump(self, drink: int, target: float, duration_ms: int) -> None:
        res = self.st.schedule_price_jump(self.st.names[drink], float(target), int(duration_ms))
        assert res["ok"], res
        self.tick()

    def crash(self, target: str, duration_ms: int) -> None:
        st = self.st
        for i, name in enumerate(st.names):
            if target == "min":
                p_target = float(st.p_min[i])
            elif target == "max":
                p_target = float(st.p_max[i])
            else:
                p_target = float(st.p0[i])
            st.schedule_price_jump(name, p_target, int(duration_ms))
        self._crash_ends.append((v1.now_ms() + max(1, int(duration_ms)), target))
        self.tick()

    # --- instrumented pieces ----------------------------------------------

    def _single_step(self, vec: NDArray[np.float64]) -> None:
        st = self.st
        _, p_q, p_mean = st.current_prices()
        if st.params.demand_enabled:
            flow = v1.expected_flow_from_price(p_q, p_mean, st.a, st.d, st.s0, st.c)
            if np.any(flow > 0):
                self.hits.add("expected_flow_nonzero")
        st.single_step(vec)
        step = st.params.step_quant
        for i in range(len(st.names)):
            lo, hi = st.p_min[i], st.p_max[i]
            if abs(p_q[i] - lo) <= _TOL and st.y[i] == _unstick_y(min(hi, lo + step), lo, hi):
                self.hits.add("unstick_up")
            if abs(p_q[i] - hi) <= _TOL and st.y[i] == _unstick_y(max(lo, hi - step), lo, hi):
                self.hits.add("unstick_down")

    def _idle(self) -> None:
        st, p, ts = self.st, self.st.params, v1.now_ms()
        rounds = st.t_round
        st.apply_idle_adjust_if_needed()
        if st.t_round == rounds:
            return
        idx = {nm: i for i, nm in enumerate(st.names)}
        for names, minutes, hit in (
            (p.idle_targets, p.idle_decay_minutes, "idle_decay"),
            (p.idle_rise_targets, p.idle_rise_minutes, "idle_rise"),
        ):
            for nm in names:
                j = idx.get(nm)
                if j is not None and ts - int(st.last_order_ts[j]) >= int(minutes * 60_000):
                    self.hits.add(hit)

    def after_event(self) -> None:
        st, ts = self.st, v1.now_ms()
        for end, target in list(self._crash_ends):
            if ts >= end:
                self._crash_ends.remove((end, target))
                _, p_q, _ = st.current_prices()
                if target == "min" and np.all(np.abs(p_q - st.p_min) <= _TOL):
                    self.hits.add("crash_end_all_p_min")

    def record(self) -> dict[str, Any]:
        st = self.st
        p_cont, p_q = v1.prices_from_y(st.y, st.p_min, st.p_max, st.params.step_quant)
        return {
            "y": st.y.tolist(),
            "p_cont": p_cont.tolist(),
            "p_q": p_q.tolist(),
            "cum_orders": st.cum_orders.tolist(),
            "flow_ema": st.flow_ema.tolist(),
            "t_round": int(st.t_round),
            "rng_counter": self.rng.counter,
        }


def _unstick_y(target: float, lo: float, hi: float) -> float:
    """The `y` an unstick branch writes, computed exactly as v1 does (engine.py:219-220)."""
    f = np.clip((target - lo) / (hi - lo), v1._FRAC_EPS, 1 - v1._FRAC_EPS)
    return float(v1._inv_sigmoid(f))


def run_v1(
    config: dict[str, Any], run_seed: int, start_ms: int, events: Sequence[Event]
) -> tuple[list[dict[str, Any]], set[str]]:
    """Replay `events` through v1; return one record per event and the branches hit."""
    with _clock(start_ms) as now:
        driver = _Driver(config, run_seed, now)
        records = []
        for event in events:
            if event["t"] < now[0]:
                raise ValueError(f"events out of order at t={event['t']}")
            now[0] = event["t"]
            kind = event["kind"]
            if kind == "tick":
                driver.tick()
            elif kind == "order":
                driver.order(np.array(event["vec"], dtype=float))
            elif kind == "jump":
                driver.jump(event["drink"], event["target"], event["duration_ms"])
            elif kind == "crash":
                driver.crash(event["target"], event["duration_ms"])
            else:
                raise ValueError(f"unknown event kind {kind!r}")
            driver.after_event()
            records.append(driver.record())
    return records, driver.hits


def capture(scenario: Scenario) -> dict[str, Any]:
    """The fixture document for `scenario`; raises `BranchNotHit` if it missed its branch."""
    records, hits = run_v1(scenario.config, scenario.run_seed, scenario.start_ms, scenario.events)
    missing = sorted(scenario.requires - hits)
    if missing:
        raise BranchNotHit(
            f"{scenario.name} no longer reaches: " + "; ".join(f"{m} ({_HITS[m]})" for m in missing)
        )
    return {
        "name": scenario.name,
        "description": scenario.description,
        "run_seed": scenario.run_seed,
        "start_ms": scenario.start_ms,
        "config": scenario.config,
        "requires": sorted(scenario.requires),
        "hits": sorted(hits),
        "events": list(scenario.events),
        "records": records,
    }


def dumps(doc: dict[str, Any]) -> str:
    """JSON with one event or record per line, so a fixture diff points at the event.

    Floats go through `json`'s `repr`, which round-trips every float64 exactly (D13).
    """

    def compact(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"))

    lines = ["{"]
    for n, (key, value) in enumerate(doc.items()):
        comma = "," if n < len(doc) - 1 else ""
        if key in ("events", "records"):
            lines.append(f"  {json.dumps(key)}: [")
            body = [compact(item) for item in value]
            lines.extend(f"    {b}{',' if i < len(body) - 1 else ''}" for i, b in enumerate(body))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {compact(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def fixture_path(name: str) -> Path:
    return FIXTURES_DIR / f"{name}.json"


def load_fixture(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(fixture_path(name).read_text(encoding="utf-8"))
    return doc


def first_difference(expected: Any, actual: Any, path: str = "") -> str | None:
    """The path of the first value that differs, e.g. `records[7].p_q[3]`; None if equal.

    Exact equality throughout -- never a tolerance (D13).
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in list(expected) + [k for k in actual if k not in expected]:
            sub = f"{path}.{key}" if path else str(key)
            if key not in expected or key not in actual:
                return sub
            found = first_difference(expected[key], actual[key], sub)
            if found:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            found = first_difference(e, a, f"{path}[{i}]")
            if found:
                return found
        return None if len(expected) == len(actual) else f"{path}[len]"
    if type(expected) is not type(actual) or expected != actual:
        return path or "<root>"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.engine.golden.capture")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write every fixture")
    mode.add_argument("--check", action="store_true", help="recapture and diff, exit 1 on change")
    args = parser.parse_args(argv)

    FIXTURES_DIR.mkdir(exist_ok=True)
    failed = False
    for scenario in SCENARIOS:
        text = dumps(capture(scenario))
        path = fixture_path(scenario.name)
        if args.write:
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.name} ({len(scenario.events)} events)")
            continue
        if not path.exists():
            print(f"{scenario.name}: no fixture at {path}")
            failed = True
            continue
        diff = first_difference(load_fixture(scenario.name), json.loads(text))
        print(f"{scenario.name}: {'ok' if diff is None else 'DIFFERS at ' + diff}")
        failed = failed or diff is not None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

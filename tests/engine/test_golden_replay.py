"""AC1: the pure engine replays every golden fixture exactly (Phase 1 plan T7).

`y`, `p_cont` and `p_q` after every event must be `np.array_equal` to what v1
produced -- full float precision, never a tolerance (D13). `cum_orders`,
`flow_ema`, `t_round` and `rng_counter` are held equal too: stricter than AC1,
and a mismatch there points at the cause of a price mismatch to come.

A failure here is a golden-fixture divergence: a hard stop. Report the first
differing event; never adjust the engine or the fixture to fit.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from tests.engine.golden import capture, replay
from tests.engine.golden.scenarios import SCENARIOS, Scenario

PRICES = ("y", "p_cont", "p_q")
ALSO = ("cum_orders", "flow_ema", "t_round", "rng_counter")


Records = list[dict[str, Any]]


def _first_divergence(scenario: str, want: Records, got: Records, key: str) -> str | None:
    for k, (w, g) in enumerate(zip(want, got, strict=True)):
        a, b = np.array(w[key]), np.array(g[key])
        if not np.array_equal(a, b):
            drink = int(np.flatnonzero(a != b)[0]) if a.shape and a.shape == b.shape else -1
            return (
                f"{scenario}: event {k}, {key} differs first at drink {drink}: "
                f"v1 {a.tolist()} vs v2 {b.tolist()}"
            )
    return None


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_ac1_the_engine_replays_the_golden_fixture_exactly(scenario: Scenario) -> None:
    doc = capture.load_fixture(scenario.name)
    got = replay.replay(doc["config"], doc["run_seed"], doc["start_ms"], doc["events"])
    want = doc["records"]
    assert len(got) == len(want)
    for key in PRICES + ALSO:
        divergence = _first_divergence(scenario.name, want, got, key)
        assert divergence is None, divergence


def test_the_replay_reads_the_fixture_not_the_scenario_script() -> None:
    """Events come from the committed JSON, so regenerating scripts cannot mask a change."""
    doc = capture.load_fixture("s1_live")
    assert len(doc["events"]) == len(SCENARIOS[0].events)
    assert doc["events"] == list(SCENARIOS[0].events)


def test_a_divergence_is_reported_with_scenario_event_and_drink() -> None:
    doc = capture.load_fixture("s2_jump")
    tampered = [dict(r) for r in doc["records"]]
    tampered[5] = {**tampered[5], "p_q": list(tampered[5]["p_q"])}
    tampered[5]["p_q"][2] += 0.1
    message = _first_divergence("s2_jump", doc["records"], tampered, "p_q")
    assert message is not None
    assert message.startswith("s2_jump: event 5") and "drink 2" in message

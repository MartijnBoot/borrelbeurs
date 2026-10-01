"""The golden fixtures are v1's, and they stay reproducible (Phase 1 plan T1).

Three things have to hold for AC1 to mean anything:

1. The reference engine is v1, byte for byte. `tests/engine/v1_reference/engine.py`
   is `git mv`'d from `exchange/engine.py` and pinned here by sha256 (plan D2).
   `.gitattributes` turns line-ending conversion off, so the CRLF blob v1 was
   imported with is what every platform checks out and what this hash covers.
2. The committed fixtures are what that engine produces today -- the in-process
   equivalent of `python -m tests.engine.golden.capture --check`.
3. Each scenario still reaches the branch it exists for, and the detector that
   says so can fail: a variant of the scenario with its trigger removed must be
   rejected at capture time.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tests.engine.golden import capture
from tests.engine.golden.scenarios import SCENARIOS, Scenario, by_name
from tests.engine.v1_reference import engine as v1

V1_ENGINE = Path(__file__).parent / "v1_reference" / "engine.py"
# sha256 of `exchange/engine.py` at main (b6a1b27), the v1 engine as imported.
V1_ENGINE_SHA256 = "f74f8f4bd69a3dcc9ebaeaec35861f70660fa26d6b542fd866e28f981b3b5467"


def test_the_reference_engine_is_v1_byte_for_byte() -> None:
    assert hashlib.sha256(V1_ENGINE.read_bytes()).hexdigest() == V1_ENGINE_SHA256, (
        f"{V1_ENGINE} no longer matches v1. It must never be edited; the golden fixtures "
        "rest on it (plan D2)."
    )


def test_every_scenario_has_a_fixture_and_every_fixture_a_scenario() -> None:
    on_disk = {path.stem for path in capture.FIXTURES_DIR.glob("*.json")}
    assert on_disk == {scenario.name for scenario in SCENARIOS}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_the_committed_fixture_reproduces_from_v1(scenario: Scenario) -> None:
    committed = capture.load_fixture(scenario.name)
    fresh = json.loads(capture.dumps(capture.capture(scenario)))
    assert capture.first_difference(committed, fresh) is None


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_a_fixture_records_prices_after_every_event(scenario: Scenario) -> None:
    doc = capture.load_fixture(scenario.name)
    assert len(doc["records"]) == len(doc["events"]) == len(scenario.events)
    for record in doc["records"]:
        for key in ("y", "p_cont", "p_q", "cum_orders", "flow_ema"):
            assert len(record[key]) == len(doc["records"][0]["y"])


def test_the_comparison_names_the_first_differing_event_and_drink() -> None:
    committed = capture.load_fixture("s1_live")
    tampered = json.loads(json.dumps(committed))
    tampered["records"][7]["p_q"][3] += 0.1
    assert capture.first_difference(committed, tampered) == "records[7].p_q[3]"


def _without(scenario: Scenario, *kinds: str) -> Scenario:
    events = tuple(e for e in scenario.events if e["kind"] not in kinds)
    return dataclasses.replace(scenario, events=events)


def _with_params(scenario: Scenario, **params: object) -> Scenario:
    config = json.loads(json.dumps(scenario.config))
    config.setdefault("params", {}).update(params)
    return dataclasses.replace(scenario, config=config)


# Each scenario with the one thing that makes it reach its branch taken away.
DEFANGED = [
    pytest.param(_without(by_name("s2_jump"), "jump"), "bm_during_jump", id="s2-no-jump"),
    pytest.param(_without(by_name("s3_bounds"), "order"), "unstick_up", id="s3-no-orders"),
    pytest.param(
        _with_params(by_name("s4_default"), demand_enabled=False),
        "expected_flow_nonzero",
        id="s4-demand-off",
    ),
    pytest.param(_without(by_name("s5_crash"), "crash"), "crash_end_all_p_min", id="s5-no-crash"),
    pytest.param(_with_params(by_name("s6_idle"), idle_targets=[]), "idle_decay", id="s6-no-decay"),
    pytest.param(
        _with_params(by_name("s6_idle"), idle_rise_targets=[]), "idle_rise", id="s6-no-rise"
    ),
]


@pytest.mark.parametrize(("scenario", "missing"), DEFANGED)
def test_capture_rejects_a_scenario_that_misses_its_branch(
    scenario: Scenario, missing: str
) -> None:
    with pytest.raises(capture.BranchNotHit, match=missing):
        capture.capture(scenario)


@pytest.mark.parametrize("scenario", SCENARIOS[1:], ids=lambda s: s.name)
def test_scenarios_two_to_six_each_name_their_branch(scenario: Scenario) -> None:
    assert scenario.requires


def test_the_rng_shim_derives_each_draw_from_seed_and_counter() -> None:
    """Plan D1: draw k is `default_rng(SeedSequence([run_seed, k])).normal(...)`."""
    shim = capture.CounterRng(run_seed=42)
    first = shim.normal(0.0, 0.3, size=6)
    second = shim.normal(0.0, 0.3, size=6)
    expected = np.random.default_rng(np.random.SeedSequence([42, 0])).normal(0.0, 0.3, 6)
    assert np.array_equal(first, expected)
    assert not np.array_equal(first, second)
    assert shim.counter == 2


def test_capture_restores_the_reference_clock() -> None:
    original = v1.now_ms
    capture.capture(by_name("s2_jump"))
    assert v1.now_ms is original

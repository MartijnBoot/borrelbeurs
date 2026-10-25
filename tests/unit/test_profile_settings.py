"""The 22 settings a profile holds, under today's `PATCH config` rules (B-04 T2).

SD1 names the 22; SD9 checks them on save and on apply, a missing one keeps its
base value and an unknown key is ignored (AC4, AC6, AC14, AC15; plan PD1-PD3).
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

from app.db.runs import DEFAULT_PARAMS
from app.runtime.config_patch import (
    PROFILE_FIELDS,
    InvalidConfig,
    profile_patch,
    profile_settings,
)
from exchange import Params

# SD1, literally: the guard against a future `ParamsPatch` field being swept in.
SD1_FIELDS = frozenset(
    {
        "step_quant",
        "eta",
        "K",
        "lambda_orders",
        "alpha_price",
        "phi_persist",
        "decay_rho",
        "history_window_minutes",
        "refresh_minutes",
        "candle_interval_s",
        "bm_enabled",
        "bm_sigma_y",
        "bm_dt_minutes",
        "flow_vol_amp",
        "flow_beta",
        "y_clip",
        "demand_enabled",
        "auto_calibrate_s0",
        "idle_decay_minutes",
        "idle_strength",
        "idle_rise_minutes",
        "idle_rise_strength",
    }
)

SOURCES: tuple[Literal["run", "profile"], ...] = ("run", "profile")


def _faults(error: InvalidConfig) -> list[dict[str, Any]]:
    faults = error.extra["faults"]
    assert isinstance(faults, list)
    return [dict(fault) for fault in faults]  # type: ignore[arg-type]


def test_a_profile_holds_exactly_sd1s_22() -> None:
    assert len(PROFILE_FIELDS) == 22
    assert set(PROFILE_FIELDS) == SD1_FIELDS


@pytest.mark.parametrize(
    "excluded",
    [
        "idle_targets",
        "idle_rise_targets",
        "bm_sigma",
        "tick_interval_ms",
        "quote_grace_versions",
        "run_seed",
        "name",
    ],
)
def test_a_profile_never_holds(excluded: str) -> None:
    """AC6."""
    assert excluded not in PROFILE_FIELDS


@pytest.mark.parametrize("params", [DEFAULT_PARAMS, Params()], ids=["DEFAULT_PARAMS", "Params()"])
def test_a_snapshot_is_the_22_and_passes_todays_rules(params: Params) -> None:
    snapshot = profile_settings(params, 60_000)

    assert set(snapshot) == SD1_FIELDS
    assert snapshot["candle_interval_s"] == 60
    assert snapshot["eta"] == params.eta
    assert snapshot["demand_enabled"] is params.demand_enabled
    patch = profile_patch(snapshot, source="run")
    assert patch.candle_interval_s == 60
    assert patch.params is not None
    assert patch.params.model_dump(exclude_unset=True) == {
        name: value for name, value in snapshot.items() if name != "candle_interval_s"
    }


def test_a_snapshot_floors_kaarsbreedte_to_whole_seconds() -> None:
    """PD3: as the config document shows it (`candle_interval_ms // 1000`)."""
    assert profile_settings(DEFAULT_PARAMS, 30_000)["candle_interval_s"] == 30


@pytest.mark.parametrize("source", SOURCES)
def test_a_param_outside_the_rules_is_422_naming_it(source: Literal["run", "profile"]) -> None:
    """AC4, AC14: the envelope `faultsOf` reads, `loc[-1]` the field."""
    settings = profile_settings(DEFAULT_PARAMS, 60_000) | {"y_clip": 25}

    with pytest.raises(InvalidConfig) as raised:
        profile_patch(settings, source=source)

    assert (raised.value.status_code, raised.value.code) == (422, "invalid_request")
    (fault,) = _faults(raised.value)
    assert fault["loc"][0] == source
    assert fault["loc"][-1] == "y_clip"
    assert "y_clip" in str(raised.value)


@pytest.mark.parametrize("source", SOURCES)
def test_a_kaarsbreedte_outside_the_rules_is_422_naming_it(
    source: Literal["run", "profile"],
) -> None:
    with pytest.raises(InvalidConfig) as raised:
        profile_patch({"candle_interval_s": 7}, source=source)

    (fault,) = _faults(raised.value)
    assert fault["loc"] == [source, "candle_interval_s"]


def test_every_failing_field_is_named() -> None:
    with pytest.raises(InvalidConfig) as raised:
        profile_patch({"y_clip": 25, "decay_rho": 2.0}, source="profile")

    assert sorted(fault["loc"][-1] for fault in _faults(raised.value)) == ["decay_rho", "y_clip"]


def test_a_missing_field_is_left_unset() -> None:
    """AC15: so it keeps its base value."""
    settings = profile_settings(DEFAULT_PARAMS, 60_000)
    del settings["eta"]

    patch = profile_patch(settings, source="profile")

    assert patch.params is not None
    assert "eta" not in patch.params.model_fields_set
    assert len(patch.params.model_fields_set) == 20
    assert patch.candle_interval_s == 60


@pytest.mark.parametrize("extra", [{"bm_sigma": 1}, {"foo": "bar"}, {"idle_targets": [1, 2]}])
def test_a_key_outside_the_22_is_ignored(extra: dict[str, Any]) -> None:
    """AC15: never read, so never a 422 either."""
    patch = profile_patch({"eta": 0.5} | extra, source="profile")

    assert patch.params is not None
    assert patch.params.model_dump(exclude_unset=True) == {"eta": 0.5}


def test_an_empty_profile_is_an_empty_patch() -> None:
    patch = profile_patch({}, source="profile")

    assert patch.model_fields_set == set()
    assert (patch.name, patch.candle_interval_s, patch.params) == (None, None, None)

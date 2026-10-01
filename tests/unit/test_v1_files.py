"""v1 file parsing and the exact-cents rule, without a database (Phase 2 T3).

AC10 and AC16 (import-mapping halves), SD7, SD13, SD15 validation, PD11-PD13.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.cli.v1_files import (
    InexactCents,
    UnknownDrinkName,
    V1Config,
    build_plan,
    euro_to_cents,
    load_plan,
    normalise_level,
    resolve_bar_prices,
)
from exchange import Params

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_CONFIG_PATH = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
LIVE_NEWS_PATH = REPO_ROOT / "legacy" / "v1" / "static" / "news.json"


def _live() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(LIVE_CONFIG_PATH.read_text(encoding="utf-8"))
    return data


# --- the real v1 files ----------------------------------------------------------


def test_the_real_v1_files_parse() -> None:
    plan = load_plan(LIVE_CONFIG_PATH, news_path=LIVE_NEWS_PATH)
    live = _live()

    assert [d.name for d in plan.drinks] == live["names"]
    assert [d.slot for d in plan.drinks] == list(range(len(live["names"])))
    assert [d.p0_cents for d in plan.drinks] == [260, 450, 600, 150, 360, 970]
    assert [d.p_min_cents for d in plan.drinks] == [150, 300, 300, 100, 100, 700]
    assert [d.p_max_cents for d in plan.drinks] == [500, 650, 700, 300, 400, 1200]
    for key in ("a", "d", "s0", "c"):
        assert [getattr(d, key) for d in plan.drinks] == live[key]
    assert plan.params == Params.from_dict(live["params"])
    # No bar_price key and no sidecar: every bar price is p0 (PD11).
    assert [d.bar_price_cents for d in plan.drinks] == [d.p0_cents for d in plan.drinks]
    assert plan.news == ()


def test_news_is_optional() -> None:
    assert load_plan(LIVE_CONFIG_PATH).news == ()


# --- SD7: euro values convert exactly or not at all -----------------------------


@pytest.mark.parametrize(
    ("value", "cents"), [(2.6, 260), (0.1, 10), (0, 0), (12.0, 1200), (9.7, 970), (0.29, 29)]
)
def test_whole_cents_convert_exactly(value: float, cents: int) -> None:
    assert euro_to_cents(value, drink="Bier", field="p0") == cents


@pytest.mark.parametrize("value", [1.005, 2.675, 1e-3, 0.125])
def test_a_fraction_of_a_cent_is_rejected_naming_drink_and_field(value: float) -> None:
    with pytest.raises(InexactCents, match=r"Wijn.*p_max") as raised:
        euro_to_cents(value, drink="Wijn", field="p_max")

    assert isinstance(raised.value, ValueError)


def test_an_inexact_cent_in_the_config_fails_the_plan() -> None:
    """AC10's mapping half: the error names the drink and the field."""
    config = _live()
    config["p_max"][1] = 6.505

    with pytest.raises(InexactCents, match=r"Wijn.*p_max"):
        build_plan(config)


# --- PD11, PD12: bar-price precedence -------------------------------------------


def test_p0_is_the_bar_price_when_nothing_overrides_it() -> None:
    assert resolve_bar_prices(V1Config.model_validate(_live()), None)["Bier"] == 260


def test_the_configs_bar_price_key_overrides_p0() -> None:
    config = _live()
    config["bar_price"] = {"Bier": 2.0}

    prices = resolve_bar_prices(V1Config.model_validate(config), None)

    assert prices["Bier"] == 200
    assert prices["Wijn"] == 450


def test_the_sidecar_overrides_the_configs_bar_price_key() -> None:
    config = _live()
    config["bar_price"] = {"Bier": 2.0, "Wijn": 4.0}

    prices = resolve_bar_prices(V1Config.model_validate(config), {"Bier": 1.5})

    assert prices["Bier"] == 150
    assert prices["Wijn"] == 400
    assert prices["Fris"] == 360


@pytest.mark.parametrize("where", ["config", "sidecar"])
def test_an_unknown_name_in_a_bar_price_map_is_rejected(where: str) -> None:
    config = _live()
    sidecar = None
    if where == "config":
        config["bar_price"] = {"Biertje": 2.0}
    else:
        sidecar = {"Biertje": 2.0}

    with pytest.raises(UnknownDrinkName, match="Biertje"):
        resolve_bar_prices(V1Config.model_validate(config), sidecar)


def test_an_inexact_bar_price_is_rejected() -> None:
    with pytest.raises(InexactCents, match=r"Bier.*bar_price"):
        resolve_bar_prices(V1Config.model_validate(_live()), {"Bier": 2.005})


def test_the_plan_carries_the_resolved_bar_prices() -> None:
    plan = build_plan(_live(), sidecar={"Fris": 3.0})

    assert {d.name: d.bar_price_cents for d in plan.drinks}["Fris"] == 300


# --- PD13, SD13: news levels -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "level"),
    [
        ("Danger", "danger"),
        ("danger", "danger"),
        ("DANGER", "danger"),
        ("Info", "info"),
        ("Success", "success"),
        ("Warning", "warning"),
    ],
)
def test_the_four_levels_are_accepted_in_any_case(raw: str, level: str) -> None:
    assert normalise_level(raw) == level


@pytest.mark.parametrize("raw", ["Critical", "", " info", "warn", 3, None])
def test_any_other_level_is_rejected(raw: object) -> None:
    with pytest.raises(ValueError, match="level"):
        normalise_level(raw)


def test_news_items_are_lowercased_in_the_plan() -> None:
    news = [
        {"id": "1-11111", "ts_ms": 1, "level": "Danger", "text": "MARKTCRASH!"},
        {"id": "2-22222", "ts_ms": 2, "level": "info", "text": "Welkom"},
    ]

    plan = build_plan(_live(), news=news)

    assert [(n.ts_ms, n.level, n.text) for n in plan.news] == [
        (1, "danger", "MARKTCRASH!"),
        (2, "info", "Welkom"),
    ]


def test_a_news_item_with_an_unknown_level_fails_the_plan() -> None:
    news = [{"id": "1-11111", "ts_ms": 1, "level": "Critical", "text": "x"}]

    with pytest.raises(ValidationError, match="level"):
        build_plan(_live(), news=news)


# --- shape validation -------------------------------------------------------------


@pytest.mark.parametrize("key", ["p_min", "p_max", "p0", "a", "d", "s0", "c"])
def test_arrays_of_unequal_length_are_rejected(key: str) -> None:
    config = _live()
    config[key] = config[key][:-1]

    with pytest.raises(ValidationError, match=key):
        build_plan(config)


def test_a_missing_array_is_rejected() -> None:
    config = _live()
    del config["s0"]

    with pytest.raises(ValidationError, match="s0"):
        build_plan(config)


def test_an_unknown_params_key_is_rejected() -> None:
    config = _live()
    config["params"]["bogus_knob"] = 1.0

    with pytest.raises(ValueError, match="bogus_knob"):
        build_plan(config)


def test_an_unknown_top_level_key_is_rejected() -> None:
    config = _live()
    config["prices"] = [1.0]

    with pytest.raises(ValidationError, match="prices"):
        build_plan(config)


def test_a_non_numeric_price_is_rejected() -> None:
    config = _live()
    config["p0"] = [*config["p0"][:-1], "9.7"]

    with pytest.raises(ValidationError, match="p0"):
        build_plan(config)


def test_building_a_plan_does_not_mutate_its_input() -> None:
    config = _live()
    original = copy.deepcopy(config)

    build_plan(config, news=[], sidecar={"Bier": 2.0})

    assert config == original

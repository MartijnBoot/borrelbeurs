"""B-01's quoted start values and ranges, against the code they quote (T4: SD5, SD8.1; AC14, AC15).

T3 pins the JSON to the spec; this pins the JSON's numbers to the code. Every
"Eerste borrel:", "Standaard:" and "Leeg bij toevoegen:" value must equal the
default it names, and every "Toegestaan:" range is rendered from the server's
pydantic validation and must equal the text exactly. `mismatches` holds every
rule; the last two tests prove it fires on a changed default and a changed range.
B-03's E34-E39 are run parameters, so the existing rules cover them (B-03 AC15).
B-06's E40-E41 are run columns with rules of their own (T17, PD17).
B-07 (T8: SD11; AC16) adds the grid to E17 and E19 and the collision to E1,
each phrase asserted only while its probe of the code holds.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast, get_args, get_origin

from pydantic import AfterValidator, BaseModel, Field
from pydantic.fields import FieldInfo

from app.api.market import EventRequest, JumpRequest
from app.db.mapping import DrinkRow
from app.db.models import Run
from app.db.runs import DEFAULT_PARAMS
from app.runtime.config import ConfigPatch, InvalidConfig, ParamsPatch, _whole_cents
from app.runtime.drinks import (
    DEFAULT_A,
    DEFAULT_C,
    DEFAULT_D,
    DEFAULT_S0,
    DrinkCreate,
    _bar_price,
    check_bounds,
)
from app.runtime.manipulation import DEFAULT_EVENT_MS
from app.runtime.price_grid import BoundsCollision, grid_faults, move_inward
from exchange import Params

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURES = REPO_ROOT / "web" / "src" / "features"


class Entry(TypedDict):
    id: str
    name: str
    paragraphs: list[str]


def _entries() -> dict[str, Entry]:
    merged: dict[str, Entry] = {}
    for feature in ("settings", "manipulation"):
        path = FEATURES / feature / "explanations.json"
        merged.update(cast(dict[str, Entry], json.loads(path.read_text(encoding="utf-8"))))
    return merged


ENTRIES = _entries()
PARAMS_FIELDS = {f.name for f in fields(Params)}

_START = re.compile(r"(Eerste borrel|Standaard|Leeg bij toevoegen): (.*?)\.(?:\s|$)")
_ALLOWED = re.compile(r"Toegestaan: (.*?)\.(?:\s|$)")
_NUMBER = re.compile(r"^-?\d+(?:,\d+)?")


def _quoted(entry: Entry, pattern: re.Pattern[str]) -> list[tuple[str, ...]]:
    return [match.groups() for p in entry["paragraphs"] for match in pattern.finditer(p)]


def _dutch(value: float) -> str:
    """0.1 -> "0,1", 3600.0 -> "3600": the Dutch decimal comma, no trailing zeros."""
    return f"{value:f}".rstrip("0").rstrip(".").replace(".", ",")


def _number(text: str) -> float | None:
    match = _NUMBER.match(text)
    return float(match.group(0).replace(",", ".")) if match else None


def _constraints(model: type[BaseModel], name: str) -> dict[str, Any]:
    """The bounds on `model.name`, whether bare (`Cents`) or optional (`StepQuant | None`)."""
    found: dict[str, Any] = {}

    def visit(metadata: Any) -> None:
        for item in metadata:
            if isinstance(item, FieldInfo):
                visit(item.metadata)
            if isinstance(item, AfterValidator) and item.func is _whole_cents:
                found["whole_cents"] = True
            for bound in ("gt", "ge", "lt", "le", "multiple_of"):
                if getattr(item, bound, None) is not None:
                    found[bound] = getattr(item, bound)

    info = model.model_fields[name]
    visit(info.metadata)
    for arg in get_args(info.annotation):
        if get_origin(arg) is Annotated:
            visit(arg.__metadata__)
    return found


def render_range(model: type[BaseModel], name: str, scale: float = 1) -> str:
    """The "Toegestaan" phrase the server's validation of `model.name` means, in display units."""
    c = _constraints(model, name)
    assert "lt" not in c, f"{model.__name__}.{name}: no phrase for lt yet"

    def n(key: str) -> str:
        return _dutch(c[key] / scale)

    if "ge" in c and "le" in c:
        phrase = f"{n('ge')} tot en met {n('le')}"
    elif "gt" in c and "le" in c:
        phrase = f"meer dan {n('gt')} en hoogstens {n('le')}"
    elif "ge" in c:
        phrase = f"{n('ge')} of meer"
    elif "gt" in c:
        phrase = f"meer dan {n('gt')}"
    else:
        phrase = "elk getal"
    if c.get("whole_cents"):
        phrase += ", in hele centen"
    if "multiple_of" in c:
        phrase += f", in veelvouden van {n('multiple_of')}"
    return phrase


def _rejects(probe: Callable[[], None]) -> bool:
    try:
        probe()
    except InvalidConfig:
        return True
    return False


# p_min < p0 < p_max, strictly (check_bounds, app/runtime/drinks.py:132-146).
def _bounds_are_strict() -> bool:
    return (
        _rejects(lambda: check_bounds(100, 100, 200))
        and _rejects(lambda: check_bounds(100, 200, 200))
        and not _rejects(lambda: check_bounds(100, 150, 200))
    )


# B-07 SD1: a bound is a multiple of the Prijsstap (app/runtime/price_grid.py).
def _bounds_are_on_the_grid() -> bool:
    return bool(grid_faults({"p_min_cents": 124}, 10, loc=())) and not grid_faults(
        {"p_min_cents": 120}, 10, loc=()
    )


# B-07 SD4: a step that leaves a drink no room between its bounds is refused.
def _step_refuses_no_room() -> bool:
    row = DrinkRow(1, 0, "x", 160, 170, 180, 10.0, 0.6, 8.0, 0.4, 170)
    try:
        move_inward([row], 50, loc=())
    except BoundsCollision:
        return True
    return False


NO_ROOM = (
    "; niet als een drankje daardoor geen ruimte meer heeft tussen Minimumprijs, Startprijs"
    " en Maximumprijs"
)


def _candle_default_s() -> float:
    default = Run.__table__.c.candle_interval_ms.server_default
    return float(default.arg.text) / 1000


def mismatches(
    entries: dict[str, Entry],
    *,
    defaults: Params = DEFAULT_PARAMS,
    params_patch: type[ParamsPatch] = ParamsPatch,
) -> list[str]:
    """Every quoted value or range that disagrees with the code, or that nothing checks."""
    problems: list[str] = []

    def say(key: str, message: str) -> None:
        problems.append(f"{entries[key]['id']} ({key}): {message}")

    # The start value each entry must quote: (label, the code's value) or None.
    start: dict[str, tuple[str, object] | None] = {}
    # The range each entry must quote: the exact phrase, or None.
    allowed: dict[str, str | None] = {}

    for key in entries:
        if key in PARAMS_FIELDS:
            # SD14: a run parameter's start value is "Eerste borrel", never "Standaard".
            start[key] = ("Eerste borrel", getattr(defaults, key))
            ranged = isinstance(getattr(defaults, key), float)
            allowed[key] = render_range(params_patch, key) if ranged else None

    allowed["step_quant"] = render_range(params_patch, "step_quant") + (
        NO_ROOM if _step_refuses_no_room() else " (no collision check)"
    )

    start["candle_interval_s"] = ("Standaard", _candle_default_s())
    allowed["candle_interval_s"] = render_range(ConfigPatch, "candle_interval_s")

    # B-06: `create_run` turns "Wallet verplicht" on and the limit starts at 0.
    start["wallet_required"] = ("Standaard", True)
    allowed["wallet_required"] = None
    start["credit_limit_cents"] = ("Standaard", 0)
    allowed["credit_limit_cents"] = render_range(ConfigPatch, "credit_limit_cents", scale=100)

    for key, value in (("a", DEFAULT_A), ("d", DEFAULT_D), ("s0", DEFAULT_S0), ("c", DEFAULT_C)):
        start[key] = ("Leeg bij toevoegen", value)
        allowed[key] = render_range(DrinkCreate, key)

    # The relational halves are literal, and true only while check_bounds is strict.
    start["p_min_cents"] = start["p0_cents"] = start["p_max_cents"] = None
    strict = ", en lager dan de Startprijs" if _bounds_are_strict() else ", tot de Startprijs"
    grid = "een veelvoud van de Prijsstap" if _bounds_are_on_the_grid() else "(no grid check)"
    allowed["p_min_cents"] = (
        render_range(DrinkCreate, "p_min_cents", scale=100) + f", {grid}" + strict
    )
    allowed["p0_cents"] = (
        "hoger dan de Minimumprijs en lager dan de Maximumprijs"
        if _bounds_are_strict()
        else "(check_bounds is no longer strict)"
    )
    allowed["p_max_cents"] = f"{grid}, " + (
        "hoger dan de Startprijs" if _bounds_are_strict() else "(check_bounds is no longer strict)"
    )

    probe = DrinkCreate(name="x", p_min_cents=100, p0_cents=250, p_max_cents=400)
    start["bar_price_cents"] = (
        "Leeg bij toevoegen",
        "de Startprijs" if _bar_price(probe) == probe.p0_cents else "(not the Startprijs)",
    )
    allowed["bar_price_cents"] = render_range(DrinkCreate, "bar_price_cents", scale=100)

    event_default = EventRequest.model_fields["duration_ms"].default
    if event_default != DEFAULT_EVENT_MS:
        say("event_duration_s", f"EventRequest's default {event_default} != {DEFAULT_EVENT_MS}")
    start["event_duration_s"] = ("Standaard", DEFAULT_EVENT_MS / 1000)
    allowed["event_duration_s"] = render_range(EventRequest, "duration_ms", scale=1000)

    # 5 lives only in the web (PriceJumpSection); ManipulationPage.test.tsx pins that side (T9).
    start["jump_duration_s"] = ("Standaard", 5.0)
    allowed["jump_duration_s"] = render_range(JumpRequest, "duration_ms", scale=1000)

    # The inclusive [p_min, p_max] check sits inside the holder's step
    # (app/runtime/manipulation.py:72-77), unreachable without a live market;
    # tests/api/test_market.py:82-83 (149, 501 rejected) and :148 (150, 500
    # accepted) pin it, so the phrase is asserted literally.
    start["jump_target"] = None
    allowed["jump_target"] = "van de Minimumprijs tot en met de Maximumprijs van dit drankje"

    for key in ("crash", "correction", "bubble", "anchor_s0"):
        start[key] = allowed[key] = None

    for key, entry in entries.items():
        if key not in start or key not in allowed:
            say(key, "no rule checks this entry")
            continue
        quoted_start = _quoted(entry, _START)
        expected_start = start[key]
        if expected_start is None:
            if quoted_start:
                say(key, f"quotes {quoted_start} but nothing checks it")
        elif len(quoted_start) != 1:
            say(key, f"expected one {expected_start[0]!r} value, found {quoted_start}")
        else:
            label, text = quoted_start[0]
            want_label, want = expected_start
            if label != want_label:
                say(key, f"labelled {label!r}, must be {want_label!r} (SD14)")
            if isinstance(want, bool):
                if text != ("aan" if want else "uit"):
                    say(key, f"{label}: {text!r} but the code says {want}")
            elif isinstance(want, tuple):
                if want != () or text != "geen drankjes":
                    say(key, f"{label}: {text!r} but the code says {want}")
            elif isinstance(want, str):
                if text != want:
                    say(key, f"{label}: {text!r} but the code says {want!r}")
            elif _number(text) != want:
                say(key, f"{label}: {text!r} but the code says {_dutch(cast(float, want))}")
            seconds = re.search(r"\(elke (\d+) seconden\)", text)
            if seconds and not math.isclose(float(seconds.group(1)), cast(float, want) * 60):
                say(key, f"{seconds.group(0)} but {_dutch(cast(float, want))} min")

        quoted_range = [groups[0] for groups in _quoted(entry, _ALLOWED)]
        expected_range = allowed[key]
        if expected_range is None:
            if quoted_range:
                say(key, f"quotes Toegestaan {quoted_range} but nothing checks it")
        elif quoted_range != [expected_range]:
            say(key, f"Toegestaan {quoted_range} but the server allows {expected_range!r}")
    return problems


def test_every_quoted_value_and_range_matches_the_code() -> None:
    """AC14, AC15."""
    assert mismatches(ENTRIES) == []


def test_every_entry_has_a_rule() -> None:
    """No row with a quoted value or range is left unchecked (T4's autonomy note)."""
    assert len(ENTRIES) == 41  # B-01's 33, B-03's six and B-06's two
    assert not [p for p in mismatches(ENTRIES) if "nothing checks" in p or "no rule" in p]


def test_the_ranges_render_as_the_server_validates() -> None:
    assert render_range(ParamsPatch, "step_quant") == "meer dan 0 en hoogstens 5, in hele centen"
    assert render_range(ParamsPatch, "K") == "meer dan 0"
    assert render_range(ParamsPatch, "idle_decay_minutes") == "0,1 of meer"
    assert render_range(ParamsPatch, "bm_dt_minutes") == "0,05 tot en met 10"
    assert render_range(ParamsPatch, "y_clip") == "1 tot en met 20"
    assert render_range(ConfigPatch, "candle_interval_s") == (
        "5 tot en met 3600, in veelvouden van 5"
    )
    assert render_range(ConfigPatch, "credit_limit_cents", scale=100) == (
        "0 tot en met 50, in veelvouden van 0,5"
    )
    assert render_range(DrinkCreate, "a") == "elk getal"
    assert render_range(JumpRequest, "duration_ms", scale=1000) == "1 tot en met 1800"


def test_a_changed_default_is_caught() -> None:
    """The spec's "temporarily changing one default", made permanent."""
    problems = mismatches(ENTRIES, defaults=replace(DEFAULT_PARAMS, eta=0.9))
    assert problems
    assert all(p.startswith("E2 ") for p in problems), problems


def test_a_changed_range_is_caught() -> None:
    """The spec's "temporarily changing one range", made permanent."""

    class WiderRefresh(ParamsPatch):
        refresh_minutes: (
            Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.1, le=20)] | None
        ) = None

    problems = mismatches(ENTRIES, params_patch=WiderRefresh)
    assert problems
    assert all(p.startswith("E9 ") for p in problems), problems

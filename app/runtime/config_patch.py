"""The SD8 PATCH model, and the 22 settings a profile holds under its rules.

**Validation (Phase 6 SD8).** `ConfigPatch` and `ParamsPatch` have every field
optional and forbid any other key, so a non-editable param (the legacy
`bm_sigma`, `tick_interval_ms`, `quote_grace_versions`) is 422 naming it. An
explicit `null` is 422 naming the field: no field is nullable and nothing is
defaulted (AC3). Numbers are strict and finite -- a string or a bool is not a
number here, so nothing is coerced (D-03). SD8's "a-b" ranges include both ends
(the user, 2026-10-08), as v1's `settings.html` `min`/`max` did.
`candle_interval_s` is 5-3600 in steps of 5 (SD10). The six noise params are
editable since B-03, in its SD3's ranges.

**Profiles (B-04 SD1, SD9; plan PD1-PD3).** A profile is `PROFILE_FIELDS`: the
editable params but the two idle target lists (they name drinks), plus
`candle_interval_s`. `profile_settings` takes them from a run, and
`profile_patch` turns stored values into a `ConfigPatch` under the rules above.
A field the values lack stays unset, so it keeps its base value; a key outside
the 22 is never read. A value outside the rules is `InvalidConfig` naming every
failing field, under `loc[0] == source`.

This module is a leaf (pydantic, `app.core.errors`, `exchange`), so `app/db`
can validate with the same rules as `app/runtime/config.py`, which re-exports
the patch models.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.core.errors import AppError
from exchange import Params


class InvalidConfig(AppError):
    """A write that only the database can judge invalid; `faults` names the field."""

    status_code = 422
    code = "invalid_request"


def _whole_cents(step: float) -> float:
    # 0.1 * 100 == 10.000000000000002: compare to the nearest whole number of cents.
    cents = step * 100
    if abs(cents - round(cents)) > 1e-9 * max(1.0, cents):
        raise ValueError("must be a multiple of 0.01")
    return step


def _not_null(value: Any) -> Any:
    if value is None:
        raise ValueError("may not be null")
    return value


StepQuant = Annotated[
    float, Field(strict=True, allow_inf_nan=False, gt=0, le=5), AfterValidator(_whole_cents)
]
NonNegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
Fraction = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1)]
HistoryMinutes = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=1, le=240)]
RefreshMinutes = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.1, le=10)]
IdleMinutes = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.1)]
NoiseMinutes = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.05, le=10)]
NoiseClip = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=1, le=20)]
DrinkIds = list[StrictInt]
RunName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CandleSeconds = Annotated[int, Field(strict=True, ge=5, le=3600, multiple_of=5)]
# B-06 SD2: "Rood staan tot", €0,00 to €50,00 in €0,50 steps.
CreditLimitCents = Annotated[int, Field(strict=True, ge=0, le=5000, multiple_of=50)]


class ParamsPatch(BaseModel):
    """SD8's editable params. An absent field is unchanged; `None` only means absent."""

    model_config = ConfigDict(extra="forbid")

    step_quant: StepQuant | None = None
    eta: NonNegative | None = None
    K: Positive | None = None
    lambda_orders: NonNegative | None = None
    alpha_price: NonNegative | None = None
    phi_persist: NonNegative | None = None
    decay_rho: Fraction | None = None
    history_window_minutes: HistoryMinutes | None = None
    refresh_minutes: RefreshMinutes | None = None
    idle_decay_minutes: IdleMinutes | None = None
    idle_rise_minutes: IdleMinutes | None = None
    idle_strength: NonNegative | None = None
    idle_rise_strength: NonNegative | None = None
    idle_targets: DrinkIds | None = None
    idle_rise_targets: DrinkIds | None = None
    demand_enabled: StrictBool | None = None
    auto_calibrate_s0: StrictBool | None = None
    bm_enabled: StrictBool | None = None
    bm_sigma_y: NonNegative | None = None
    bm_dt_minutes: NoiseMinutes | None = None
    flow_vol_amp: NonNegative | None = None
    flow_beta: Fraction | None = None
    y_clip: NoiseClip | None = None

    _no_null = field_validator("*", mode="before")(_not_null)


class ConfigPatch(BaseModel):
    """`PATCH /api/runs/{run_id}/config` (SD5)."""

    model_config = ConfigDict(extra="forbid")

    name: RunName | None = None
    candle_interval_s: CandleSeconds | None = None
    # B-06 SD1-SD3: run columns, not engine params, so never part of a profile.
    wallet_required: StrictBool | None = None
    credit_limit_cents: CreditLimitCents | None = None
    params: ParamsPatch | None = None

    _no_null = field_validator("*", mode="before")(_not_null)


# Derived, and pinned to SD1's 22 by tests/unit/test_profile_settings.py, so a new
# `ParamsPatch` field fails a test rather than silently joining every profile.
_PROFILE_PARAMS: Final = tuple(
    name for name in ParamsPatch.model_fields if name not in ("idle_targets", "idle_rise_targets")
)
PROFILE_FIELDS: Final = (*_PROFILE_PARAMS, "candle_interval_s")


def profile_settings(params: Params, candle_interval_ms: int) -> dict[str, Any]:
    """A run's 22 as its config document shows them (PD3): Kaarsbreedte in whole seconds."""
    return {name: getattr(params, name) for name in _PROFILE_PARAMS} | {
        "candle_interval_s": candle_interval_ms // 1000
    }


def profile_patch(settings: Mapping[str, Any], *, source: Literal["run", "profile"]) -> ConfigPatch:
    """`settings`' fields among the 22 as a validated patch, or `InvalidConfig` (PD2)."""
    body: dict[str, Any] = {}
    params = {name: settings[name] for name in _PROFILE_PARAMS if name in settings}
    if params:
        body["params"] = params
    if "candle_interval_s" in settings:
        body["candle_interval_s"] = settings["candle_interval_s"]
    try:
        return ConfigPatch.model_validate(body)
    except ValidationError as error:
        locs = [[source, *(str(part) for part in e["loc"])] for e in error.errors()]
        msgs = [str(e["msg"]) for e in error.errors()]
        faults: list[JsonValue] = [
            {"loc": list[JsonValue](loc), "msg": msg} for loc, msg in zip(locs, msgs, strict=True)
        ]
        named = "; ".join(f"{loc[-1]}: {msg}" for loc, msg in zip(locs, msgs, strict=True))
        raise InvalidConfig(named, extra={"faults": faults}) from None

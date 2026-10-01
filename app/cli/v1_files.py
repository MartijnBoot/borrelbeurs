"""v1's three files, read and validated into one `ImportPlan` before anything is written.

The files are `config/exchange_config.json` (the market), `static/news.json`
(the ticker) and the optional `bar_prices.json` sidecar. Every value is checked
here, so the import (SD15) either has a complete, valid plan or writes nothing:

- **Euro amounts convert to cents exactly or not at all** (SD7, AC10). A value is
  read as `Decimal(str(value))`, the shortest decimal that round-trips the float,
  so `2.6` is 260 cents and `1.005` is an error naming the drink and the field.
- **Unknown keys are errors.** v1 ignores them; here an unknown `params` key, an
  unknown top-level key, or a drink name in a bar-price map that is not in
  `names` (PD12) fails the import, so a typo cannot silently price a drink.
- **Bar prices follow v1's precedence** (`legacy/v1/backend/api.py:167-190`,
  PD11): `p0`, overridden by the config's `bar_price` key, overridden by the
  sidecar.
- **News levels are lowercased** and anything but the four levels is rejected
  (SD13, PD13).

This is the one module outside `tests/` that reads a file (AC18): the
repositories and rehydrate never do.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, TypeAdapter, field_validator, model_validator

from exchange import Params

NewsLevel = Literal["info", "success", "warning", "danger"]
NEWS_LEVELS: tuple[NewsLevel, ...] = get_args(NewsLevel)

_PRICE_FIELDS = ("p_min", "p0", "p_max")
_COEFFICIENT_FIELDS = ("a", "d", "s0", "c")


class InexactCents(ValueError):
    """A euro value from a v1 file is not a whole number of cents (SD7)."""


class UnknownDrinkName(ValueError):
    """A bar-price map names a drink the config does not have (PD12)."""


def euro_to_cents(value: float, *, drink: str, field: str) -> int:
    """`value` euros as integer cents, or `InexactCents` naming `drink` and `field`."""
    cents = Decimal(str(value)) * 100
    if cents != cents.to_integral_value():
        raise InexactCents(f"{drink}: {field} = {value!r} is not a whole number of cents")
    return int(cents)


def normalise_level(raw: object) -> NewsLevel:
    """One of the four levels, in any case, as its lowercase form (PD13)."""
    if isinstance(raw, str) and raw.lower() in NEWS_LEVELS:
        return cast(NewsLevel, raw.lower())
    raise ValueError(f"unknown news level {raw!r}; expected one of {', '.join(NEWS_LEVELS)}")


class V1Config(BaseModel):
    """`exchange_config.json`: names, the seven per-drink arrays, params, bar prices."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    names: list[str]
    p_min: list[float]
    p_max: list[float]
    p0: list[float]
    a: list[float]
    d: list[float]
    s0: list[float]
    c: list[float]
    params: dict[str, Any]
    bar_price: dict[str, float] | None = None

    @field_validator("params")
    @classmethod
    def _known_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        """`Params.from_dict` rejects an unknown key and a non-numeric value."""
        Params.from_dict(value)
        return value

    @model_validator(mode="after")
    def _one_value_per_name(self) -> V1Config:
        n = len(self.names)
        for key in (*_PRICE_FIELDS, *_COEFFICIENT_FIELDS):
            length = len(getattr(self, key))
            if length != n:
                raise ValueError(f"{key} has {length} values, expected {n} (one per name)")
        return self


class V1NewsItem(BaseModel):
    """One entry of `news.json`, as v1's `append_news_item` writes it."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    ts_ms: int
    level: NewsLevel
    text: str

    @field_validator("level", mode="before")
    @classmethod
    def _lowercase_level(cls, value: object) -> NewsLevel:
        return normalise_level(value)


_NEWS = TypeAdapter(list[V1NewsItem])
_SIDECAR = TypeAdapter(dict[str, float])


@dataclass(frozen=True)
class ImportedDrink:
    name: str
    slot: int
    p_min_cents: int
    p0_cents: int
    p_max_cents: int
    a: float
    d: float
    s0: float
    c: float
    bar_price_cents: int


@dataclass(frozen=True)
class ImportedNews:
    ts_ms: int
    level: NewsLevel
    text: str


@dataclass(frozen=True)
class ImportPlan:
    """Everything the import writes, validated: drinks in slot order, params, news."""

    drinks: tuple[ImportedDrink, ...]
    params: Params
    news: tuple[ImportedNews, ...]


def resolve_bar_prices(config: V1Config, sidecar: Mapping[str, float] | None) -> dict[str, int]:
    """Bar price in cents per drink name: `p0`, then the config's map, then the sidecar."""
    prices = {
        name: euro_to_cents(p0, drink=name, field="p0")
        for name, p0 in zip(config.names, config.p0, strict=True)
    }
    for source, overrides in (
        ("bar_price", config.bar_price),
        ("bar_prices.json", sidecar),
    ):
        for name, euros in (overrides or {}).items():
            if name not in prices:
                raise UnknownDrinkName(f"{source} names {name!r}, which is not a drink in names")
            prices[name] = euro_to_cents(euros, drink=name, field=f"bar_price ({source})")
    return prices


def build_plan(config_data: Any, *, news: Any = None, sidecar: Any = None) -> ImportPlan:
    """Validate already-decoded file contents into an `ImportPlan`.

    Raises `ValueError` (a pydantic `ValidationError`, `InexactCents` or
    `UnknownDrinkName`) naming what is wrong; nothing is half-built.
    """
    config = V1Config.model_validate(config_data)
    items = _NEWS.validate_python(news) if news is not None else []
    bar_prices = resolve_bar_prices(
        config, _SIDECAR.validate_python(sidecar) if sidecar is not None else None
    )
    drinks = []
    for slot, name in enumerate(config.names):
        cents = {
            f"{key}_cents": euro_to_cents(getattr(config, key)[slot], drink=name, field=key)
            for key in _PRICE_FIELDS
        }
        coefficients = {key: getattr(config, key)[slot] for key in _COEFFICIENT_FIELDS}
        drinks.append(
            ImportedDrink(
                name=name,
                slot=slot,
                **cents,
                **coefficients,
                bar_price_cents=bar_prices[name],
            )
        )
    return ImportPlan(
        drinks=tuple(drinks),
        params=Params.from_dict(config.params),
        news=tuple(ImportedNews(ts_ms=i.ts_ms, level=i.level, text=i.text) for i in items),
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_plan(
    config_path: Path, *, news_path: Path | None = None, bar_prices_path: Path | None = None
) -> ImportPlan:
    """Read the v1 files and validate them into an `ImportPlan`."""
    return build_plan(
        _read_json(config_path),
        news=_read_json(news_path) if news_path is not None else None,
        sidecar=_read_json(bar_prices_path) if bar_prices_path is not None else None,
    )

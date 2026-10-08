"""The realtime protocol's messages: closed pydantic models (Phase 3 SD24, SD27, SD28).

These models are the contract (`docs/design/realtime-protocol.md`). Every one is
`extra="forbid"` and frozen, so a dead field (D-33: `prices_cont`,
`expected_demand`, `t`, `server_time_wall`) cannot be sent, and a client message
that is not one of the three below is a validation error, never a command
(SD30, D-36).

**Prices (SD24, AC23).** Integer cents in two named tracks: `price_cents`, the
`step_quant` track, shown and charged; `chart_price_cents`, the 0.01 track the
candles are drawn from. An order line's `unit_price_cents` is what was charged,
which comes from `price_cents`. Every price field is a `StrictInt`, so a float
is refused rather than truncated.

**The tick's candle is `[o, h, l, c]`** with its bucket start, `candle_t_ms`,
sent once per tick rather than per drink. Named keys put a six-drink tick at
about 790 bytes, over AC20's 600; this positional candle was chosen by
MartijnBoot on 2026-10-02 (plan R6, option D). The snapshot's `bars` keep
named fields: they are not size-bound.

**`seq` (SD27)** is the hub's: every broadcast takes the next one, a unicast
carries the current one. `version` is the committed engine version, `None` on
messages that carry no prices.

**`config` (Phase 6 SD18)** is broadcast after every committed live config
write: the run with its name, every drink with `active`, and the params as the
snapshot carries them. A removed drink stays listed with `active: false`;
`prices`, `bars` and a tick's drinks cover active drinks only.

**`theme` (Phase 4 SD9, PD3)** carries the active preset's tokens and font, so
the client holds no preset table (SD6). It carries no prices: `version` is
`None`, and the hub keeps its resync metadata from the last priced broadcast.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.runtime.theme import TOKEN_NAMES, PresetName, Theme, image_url

PROTOCOL_VERSION: Final = 1

Role = Literal["display", "bar", "admin"]
NewsLevel = Literal["info", "success", "warning", "danger"]
EventKind = Literal["crash", "bubble", "correction"]
NonNegative = Annotated[StrictInt, Field(ge=0)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- prices and candles -------------------------------------------------------


class DrinkPrice(_Closed):
    price_cents: NonNegative
    chart_price_cents: NonNegative


class TickDrink(DrinkPrice):
    # The current bucket's [open, high, low, close] on chart_price_cents.
    candle: tuple[StrictInt, StrictInt, StrictInt, StrictInt]


class Bar(_Closed):
    """One closed or open bucket of one drink, on the chart track."""

    t_ms: StrictInt
    o: StrictInt
    h: StrictInt
    l: StrictInt  # noqa: E741 -- OHLC is the protocol's own naming
    c: StrictInt


# --- server -> client data ----------------------------------------------------


class TickData(_Closed):
    candle_t_ms: StrictInt
    drinks: dict[int, TickDrink]


class RunInfo(_Closed):
    run_id: StrictInt
    tick_interval_ms: StrictInt
    candle_interval_ms: StrictInt
    quote_grace_versions: NonNegative


class ConfigRunInfo(RunInfo):
    name: str


class DrinkInfo(_Closed):
    drink_id: StrictInt
    name: str
    # False once removed from a live run (Phase 6 SD13): listed, never priced.
    active: bool


class NewsItemData(_Closed):
    news_id: StrictInt
    ts_ms: StrictInt
    level: NewsLevel
    text: str


class EarningsData(_Closed):
    qty: NonNegative
    revenue_cents: NonNegative


class MarketEventInfo(_Closed):
    event_id: StrictInt
    kind: EventKind
    drink_ids: tuple[int, ...]
    t_start_ms: StrictInt
    t_end_ms: StrictInt


class Snapshot(_Closed):
    """The whole client-visible market, built from holder memory (T19)."""

    # The engine version these prices belong to: what an HTTP poller quotes (SD18).
    version: StrictInt
    run: RunInfo
    drinks: list[DrinkInfo]
    # The engine's `Params` as JSON (`params_to_json`), as v1 sent them.
    params: dict[str, JsonValue]
    prices: dict[int, DrinkPrice]
    bars: dict[int, list[Bar]]
    news: Annotated[list[NewsItemData], Field(max_length=50)]
    earnings: dict[int, EarningsData]
    market_events: list[MarketEventInfo]


class ConfigData(_Closed):
    """A committed live config change (Phase 6 SD18); `revision` is its config revision."""

    revision: NonNegative
    run: ConfigRunInfo
    drinks: list[DrinkInfo]
    params: dict[str, JsonValue]


class OrderLineData(_Closed):
    drink_id: StrictInt
    qty: Annotated[StrictInt, Field(ge=1)]
    unit_price_cents: NonNegative
    line_total_cents: NonNegative


class OrderData(_Closed):
    """An accepted order (plan PD12): its lines, the earnings delta, every drink's new prices."""

    order_id: StrictInt
    lines: list[OrderLineData]
    total_cents: NonNegative
    earnings_delta: dict[int, EarningsData]
    prices: dict[int, DrinkPrice]


class MarketEventData(_Closed):
    op: Literal["start", "end"]
    event_id: StrictInt
    kind: EventKind
    drink_ids: tuple[int, ...]
    t_start_ms: StrictInt
    t_end_ms: StrictInt


class NewsData(_Closed):
    op: Literal["add", "delete"]
    item: NewsItemData


class ThemeImages(_Closed):
    bg: str | None
    header: str | None
    logo: str | None
    promo: str | None


class ThemeData(_Closed):
    """The active theme (PD3): `revision` 0 is "no stored row, Blauw"."""

    preset: PresetName
    revision: NonNegative
    # Exactly the manifest's 24 tokens (`app/runtime/theme.py`), name -> CSS value.
    tokens: dict[str, str]
    # The CSS font stack: EB Garamond for Oud Geld, Inter otherwise.
    font_family: str
    # Each image slot as "/assets/<id>", or null (Phase 6 PD9).
    images: ThemeImages

    @field_validator("tokens")
    @classmethod
    def _tokens_are_the_manifest(cls, tokens: dict[str, str]) -> dict[str, str]:
        if set(tokens) != set(TOKEN_NAMES):
            missing = sorted(set(TOKEN_NAMES) - set(tokens))
            extra = sorted(set(tokens) - set(TOKEN_NAMES))
            raise ValueError(f"tokens must be the manifest's: missing {missing}, extra {extra}")
        return tokens


def theme_data(theme: Theme) -> ThemeData:
    return ThemeData(
        preset=theme.preset,
        revision=theme.revision,
        tokens=dict(theme.tokens),
        font_family=theme.font_family,
        images=ThemeImages(
            bg=image_url(theme.images["bg"]),
            header=image_url(theme.images["header"]),
            logo=image_url(theme.images["logo"]),
            promo=image_url(theme.images["promo"]),
        ),
    )


class Hello(_Closed):
    boot_id: str
    run_id: StrictInt | None
    tick_interval_ms: StrictInt
    protocol: StrictInt
    role: Role
    theme: ThemeData


class Pong(_Closed):
    server_ts_ms: StrictInt


class Resync(_Closed):
    """ "You are too far behind, or I restarted": reconnect or `resync_request`."""


class ErrorData(_Closed):
    code: str


ServerMessageType = Literal[
    "hello",
    "snapshot",
    "tick",
    "order",
    "market_event",
    "news",
    "pong",
    "resync",
    "error",
    "theme",
    "config",
]

SERVER_MESSAGE_MODELS: Final[dict[str, type[_Closed]]] = {
    "hello": Hello,
    "snapshot": Snapshot,
    "tick": TickData,
    "order": OrderData,
    "market_event": MarketEventData,
    "news": NewsData,
    "pong": Pong,
    "resync": Resync,
    "error": ErrorData,
    "theme": ThemeData,
    "config": ConfigData,
}

ServerData = (
    Hello
    | Snapshot
    | TickData
    | OrderData
    | MarketEventData
    | NewsData
    | Pong
    | Resync
    | ErrorData
    | ThemeData
    | ConfigData
)


class Envelope(_Closed):
    """`{v, type, seq, ts_ms, run_id, version, data}`; `type` names `data`'s model."""

    v: Literal[1] = PROTOCOL_VERSION
    type: ServerMessageType
    seq: NonNegative
    ts_ms: StrictInt
    run_id: StrictInt | None
    version: NonNegative | None
    data: ServerData

    @model_validator(mode="before")
    @classmethod
    def _data_matches_type(cls, values: Any) -> Any:
        """Validate `data` as exactly the model `type` names, not the first union match."""
        if isinstance(values, dict) and values.get("type") in SERVER_MESSAGE_MODELS:
            model = SERVER_MESSAGE_MODELS[values["type"]]
            data = values.get("data")
            if isinstance(data, BaseModel) and not isinstance(data, model):
                raise ValueError(f"a {values['type']} envelope needs {model.__name__} data")
            if not isinstance(data, BaseModel):
                values = {**values, "data": model.model_validate(data)}
        return values


# --- client -> server -----------------------------------------------------------


class ClientHello(_Closed):
    type: Literal["hello"] = "hello"
    boot_id: str
    last_seq: NonNegative


class ClientPing(_Closed):
    type: Literal["ping"] = "ping"


class ClientResyncRequest(_Closed):
    type: Literal["resync_request"] = "resync_request"


ClientMessage = Annotated[
    ClientHello | ClientPing | ClientResyncRequest, Field(discriminator="type")
]

_client_messages: TypeAdapter[ClientHello | ClientPing | ClientResyncRequest] = TypeAdapter(
    ClientMessage
)


def parse_client_message(raw: str) -> ClientHello | ClientPing | ClientResyncRequest:
    """One client frame, or `ValidationError` for invalid JSON or any other shape (SD30)."""
    return _client_messages.validate_json(raw)

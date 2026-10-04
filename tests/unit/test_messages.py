"""The closed realtime message models (Phase 3 T11: SD24, SD27, SD28; AC20, AC20a, AC23; PD12)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.db.mapping import params_to_json
from app.realtime.messages import (
    PROTOCOL_VERSION,
    SERVER_MESSAGE_MODELS,
    Bar,
    ClientHello,
    ClientMessage,
    ClientPing,
    ClientResyncRequest,
    DrinkInfo,
    DrinkPrice,
    EarningsData,
    Envelope,
    ErrorData,
    Hello,
    MarketEventData,
    MarketEventInfo,
    NewsData,
    NewsItemData,
    OrderData,
    OrderLineData,
    Pong,
    Resync,
    RunInfo,
    ServerData,
    ServerMessageType,
    Snapshot,
    ThemeData,
    TickData,
    TickDrink,
    parse_client_message,
    theme_data,
)
from app.runtime.theme import TOKEN_NAMES, resolve
from exchange import Params

TS = 1_759_312_800_000
DRINK_IDS = (101, 102, 103, 104, 105, 106)
DEAD_FIELDS = frozenset(
    {"prices_cont", "expected_demand", "t", "server_time_wall", "prices_quant", "history", "series"}
)
# Fields carrying a market price (AC23): the two tracks, and an order line's
# charged price, which comes from `price_cents` (SD18, SD24).
PRICE_FIELDS = frozenset({"price_cents", "chart_price_cents", "unit_price_cents"})


def _tick(*, seq: int, version: int) -> Envelope:
    return Envelope(
        type="tick",
        seq=seq,
        ts_ms=TS + 59_000,
        run_id=12,
        version=version,
        data=TickData(
            candle_t_ms=TS,
            drinks={
                drink_id: TickDrink(
                    price_cents=250, chart_price_cents=253, candle=(240, 290, 210, 253)
                )
                for drink_id in DRINK_IDS
            },
        ),
    )


def test_a_six_drink_tick_is_at_most_600_bytes() -> None:
    """AC20, with option D (2026-10-02): the candle is `[o, h, l, c]`, its bucket start sent once.

    Realistic late-evening magnitudes: three-digit drink ids and cents, six-digit
    seq and version.
    """
    frame = _tick(seq=999_999, version=999_999).model_dump_json()

    assert len(frame.encode("utf-8")) <= 600, len(frame)


def test_a_tick_carries_only_version_ts_and_per_drink_prices_and_candle() -> None:
    """AC20: no history, news or per-sale series."""
    dumped = _tick(seq=1, version=1).model_dump(mode="json")

    assert set(dumped) == {"v", "type", "seq", "ts_ms", "run_id", "version", "data"}
    assert set(dumped["data"]) == {"candle_t_ms", "drinks"}
    assert set(dumped["data"]["drinks"]["101"]) == {"price_cents", "chart_price_cents", "candle"}
    assert dumped["data"]["drinks"]["101"]["candle"] == [240, 290, 210, 253]


def _schemas() -> Iterator[tuple[str, dict[str, Any]]]:
    models: list[type[BaseModel]] = [*SERVER_MESSAGE_MODELS.values(), Envelope]
    for model in models:
        yield model.__name__, model.model_json_schema()
    yield "ClientMessage", TypeAdapter(ClientMessage).json_schema()


def _property_names(schema: Any) -> Iterator[str]:
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                yield from value
            yield from _property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _property_names(item)


def test_no_message_has_a_dead_field() -> None:
    """AC20a (D-33), by a recursive walk over every model's JSON schema."""
    for name, schema in _schemas():
        found = DEAD_FIELDS & set(_property_names(schema))
        assert not found, f"{name} has {sorted(found)}"


def test_the_walk_sees_nested_fields() -> None:
    """Anti-vacuity: the walk reaches a field three models deep."""
    names = set(_property_names(Snapshot.model_json_schema()))

    assert {"revenue_cents", "price_cents", "t_ms", "drink_ids", "level"} <= names


def test_the_snapshots_params_hold_no_dead_field() -> None:
    """`params` is the engine's `Params` as JSON; its keys are outside the schema walk."""
    assert not DEAD_FIELDS & set(params_to_json(Params()))


def test_the_snapshot_carries_per_drink_earnings() -> None:
    """AC20a: `revenue_per_drink` survives as the earnings aggregate."""
    assert "earnings" in Snapshot.model_fields
    assert set(EarningsData.model_fields) == {"qty", "revenue_cents"}


def _number_types(schema: Any, path: str = "") -> Iterator[str]:
    if isinstance(schema, dict):
        if schema.get("type") == "number":
            yield path
        for key, value in schema.items():
            yield from _number_types(value, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, item in enumerate(schema):
            yield from _number_types(item, f"{path}[{i}]")


def test_no_message_field_is_a_float() -> None:
    """AC23: every price, and every other number on the wire, is an integer."""
    for name, schema in _schemas():
        assert list(_number_types(schema)) == [], name


def _price_like(schema: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                for prop, sub in value.items():
                    # `prices` maps drink_id to DrinkPrice: a container, not a price.
                    if "price" in prop and sub.get("type") != "object":
                        yield prop, sub
            yield from _price_like(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _price_like(item)


def test_every_price_field_is_an_integer_named_for_its_track() -> None:
    """AC23: a price is `price_cents`, `chart_price_cents`, a charged `unit_price_cents`,
    or a candle's o/h/l/c -- never anything else, never a float."""
    seen: set[str] = set()
    for name, schema in _schemas():
        for prop, sub in _price_like(schema):
            seen.add(prop)
            assert prop in PRICE_FIELDS, f"{name}.{prop} is not a named price track"
            assert sub.get("type") == "integer", f"{name}.{prop} is {sub}"
    assert seen == PRICE_FIELDS
    assert set(Bar.model_fields) == {"t_ms", "o", "h", "l", "c"}


def test_a_float_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DrinkPrice(price_cents=2.5, chart_price_cents=253)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        DrinkPrice(price_cents=250.0, chart_price_cents=253)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "model",
    [
        DrinkPrice,
        TickData,
        Snapshot,
        OrderData,
        MarketEventData,
        NewsData,
        Hello,
        Pong,
        ErrorData,
        ThemeData,
    ],
)
def test_extra_keys_are_rejected(model: type[BaseModel]) -> None:
    """SD28: every model is closed."""
    assert model.model_config.get("extra") == "forbid"
    assert model.model_config.get("frozen") is True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({"prices_cont": [1.0]})


def test_an_envelopes_type_must_match_its_data() -> None:
    with pytest.raises(ValidationError, match="tick"):
        Envelope(type="tick", seq=1, ts_ms=TS, run_id=1, version=1, data=Pong(server_ts_ms=TS))


def test_every_server_type_round_trips() -> None:
    news = NewsItemData(news_id=1, ts_ms=TS, level="info", text="x")
    prices = {101: DrinkPrice(price_cents=250, chart_price_cents=253)}
    samples: dict[ServerMessageType, ServerData] = {
        "hello": Hello(
            boot_id="ab12",
            run_id=None,
            tick_interval_ms=1000,
            protocol=1,
            role="bar",
            theme=theme_data(resolve("blauw", 0)),
        ),
        "snapshot": Snapshot(
            version=7,
            run=RunInfo(
                run_id=1, tick_interval_ms=1000, candle_interval_ms=60_000, quote_grace_versions=2
            ),
            drinks=[DrinkInfo(drink_id=101, name="Bier")],
            params=params_to_json(Params()),
            prices=prices,
            bars={101: [Bar(t_ms=TS, o=240, h=290, l=210, c=253)]},
            news=[news],
            earnings={101: EarningsData(qty=3, revenue_cents=750)},
            market_events=[
                MarketEventInfo(
                    event_id=1, kind="crash", drink_ids=(101,), t_start_ms=TS, t_end_ms=TS + 1
                )
            ],
        ),
        "tick": _tick(seq=1, version=1).data,
        "order": OrderData(
            order_id=1,
            lines=[OrderLineData(drink_id=101, qty=3, unit_price_cents=250, line_total_cents=750)],
            total_cents=750,
            earnings_delta={101: EarningsData(qty=3, revenue_cents=750)},
            prices=prices,
        ),
        "market_event": MarketEventData(
            op="start", event_id=1, kind="bubble", drink_ids=(101,), t_start_ms=TS, t_end_ms=TS + 1
        ),
        "news": NewsData(op="add", item=news),
        "pong": Pong(server_ts_ms=TS),
        "resync": Resync(),
        "error": ErrorData(code="unknown_message"),
        "theme": theme_data(resolve("oudgeld", 3)),
    }
    assert set(samples) == set(SERVER_MESSAGE_MODELS)
    for kind, data in samples.items():
        frame = Envelope(type=kind, seq=7, ts_ms=TS, run_id=None, version=None, data=data)
        raw = frame.model_dump_json()
        again = Envelope.model_validate_json(raw)
        assert again.model_dump_json() == raw, kind
        assert again.v == PROTOCOL_VERSION


def test_the_snapshot_holds_at_most_fifty_news_items() -> None:
    item = NewsItemData(news_id=1, ts_ms=TS, level="info", text="x")
    fields = Snapshot.model_json_schema()["properties"]["news"]

    assert fields["maxItems"] == 50
    assert item.level == "info"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '{"type": "hello", "boot_id": "ab12", "last_seq": 41}',
            ClientHello(boot_id="ab12", last_seq=41),
        ),
        ('{"type": "ping"}', ClientPing()),
        ('{"type": "resync_request"}', ClientResyncRequest()),
    ],
)
def test_the_three_client_messages_parse(raw: str, expected: BaseModel) -> None:
    assert parse_client_message(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "state",
        "",
        "{",
        '{"type": "state"}',
        '{"type": "ping", "extra": 1}',
        '{"type": "hello", "boot_id": "ab12"}',
        '{"type": "hello", "boot_id": "ab12", "last_seq": -1}',
        '{"type": "hello", "boot_id": "ab12", "last_seq": 1.5}',
        "[]",
        '"ping"',
    ],
)
def test_anything_else_is_refused(raw: str) -> None:
    """SD30: v1's literal `"state"` and every other shape is a validation error, never a command."""
    with pytest.raises(ValidationError):
        parse_client_message(raw)


# --- theme (Phase 4 T3: SD9; PD3) ----------------------------------------------


def _theme_fields(**changes: Any) -> dict[str, Any]:
    fields = theme_data(resolve("rood", 2)).model_dump()
    fields.update(changes)
    return fields


def test_theme_data_carries_pd3s_four_fields() -> None:
    assert set(ThemeData.model_fields) == {"preset", "revision", "tokens", "font_family"}


def test_theme_data_is_the_resolved_preset() -> None:
    theme = resolve("oudgeld", 4)
    data = theme_data(theme)

    assert (data.preset, data.revision, data.font_family) == ("oudgeld", 4, theme.font_family)
    assert data.tokens == dict(theme.tokens)
    assert tuple(data.tokens) == TOKEN_NAMES


def test_a_theme_envelope_needs_theme_data() -> None:
    with pytest.raises(ValidationError, match="theme"):
        Envelope(
            type="theme", seq=1, ts_ms=TS, run_id=None, version=None, data=Pong(server_ts_ms=TS)
        )


def test_a_theme_envelope_round_trips_from_json() -> None:
    frame = Envelope(
        type="theme",
        seq=4,
        ts_ms=TS,
        run_id=None,
        version=None,
        data=theme_data(resolve("groen", 1)),
    )

    again = Envelope.model_validate_json(frame.model_dump_json())

    assert isinstance(again.data, ThemeData)
    assert again == frame


@pytest.mark.parametrize(
    "tokens",
    [
        {name: "#000000" for name in TOKEN_NAMES[:-1]},
        {**{name: "#000000" for name in TOKEN_NAMES}, "--extra": "#000000"},
        {**{name: "#000000" for name in TOKEN_NAMES if name != "--bg"}, "--bgx": "#000000"},
    ],
    ids=["missing", "extra", "renamed"],
)
def test_theme_tokens_must_be_exactly_the_manifest(tokens: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="tokens"):
        ThemeData.model_validate(_theme_fields(tokens=tokens))


@pytest.mark.parametrize(
    ("field", "value"), [("preset", "eigen"), ("revision", -1), ("revision", 1.0)]
)
def test_theme_preset_and_revision_are_constrained(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ThemeData.model_validate(_theme_fields(**{field: value}))


def test_hello_carries_a_theme() -> None:
    assert Hello.model_fields["theme"].annotation is ThemeData

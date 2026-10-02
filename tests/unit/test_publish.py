"""The publisher and the snapshot (Phase 3 T19: SD24-SD26, SD28; AC19, AC20, AC23, AC18e)."""

from __future__ import annotations

import asyncio
import json
from types import MappingProxyType
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.codec import tick_prices
from app.db.news import NewsItem
from app.realtime.hub import Hub
from app.realtime.messages import Envelope, Snapshot
from app.realtime.publish import Publisher, seeded_book, snapshot
from app.runtime.earnings import DrinkEarnings, EarningsAggregate
from app.runtime.history import HistoryRing, TickEntry
from app.runtime.holder import (
    CommittedLine,
    DomainEvent,
    MarketEventEnded,
    MarketEventStarted,
    MarketHolder,
    NewsChanged,
    OrderCommitted,
    TickCommitted,
)
from app.runtime.market_events import ActiveEvent
from app.runtime.rehydrate import RehydratedRun
from exchange import DrinkSpec, MarketSpec, Params, advance, initial_state
from tests.support.clock import FakeClock

T0 = 1_759_312_800_000  # a whole minute
DRINKS = (11, 12, 13)
STEP_CENTS = 10
DEAD = {
    "prices_cont",
    "expected_demand",
    "t",
    "server_time_wall",
    "prices_quant",
    "history",
    "series",
}


class RecordingSocket:
    def __init__(self) -> None:
        self.frames: list[str] = []

    async def send_text(self, frame: str) -> None:
        self.frames.append(frame)

    async def close(self, code: int) -> None:
        pass


def _spec() -> MarketSpec:
    return MarketSpec.from_drinks(
        [
            DrinkSpec(name=n, p_min=1.5, p_max=5.0, p0=2.6, a=1.0, d=0.1, s0=1.0, c=0.1)
            for n in ("Bier", "Wijn", "Fris")
        ],
        Params(step_quant=0.1),
    )


def _entries() -> list[TickEntry]:
    spec = _spec()
    state = initial_state(spec, now_ms=T0)
    entries = [TickEntry(state.version, T0, "reset", tick_prices(spec, state, DRINKS))]
    for k, source in enumerate(("tick", "order", "tick"), start=1):
        orders = [3.0, 0.0, 1.0] if source == "order" else None
        state = advance(spec, state, now_ms=T0 + k * 1_000, orders=orders, run_seed=7).state
        entries.append(
            TickEntry(state.version, T0 + k * 1_000, source, tick_prices(spec, state, DRINKS))
        )
    return entries


def _holder(news: int = 3) -> MarketHolder:
    spec = _spec()
    ring = HistoryRing(15 * 60_000)
    ring.load(_entries())
    run = RehydratedRun(
        run_id=4,
        run_seed=7,
        spec=spec,
        state=initial_state(spec, now_ms=T0),
        drink_ids=DRINKS,
        bar_price_cents=MappingProxyType({d: 260 for d in DRINKS}),
        wall_ts_ms=T0,
        ring=ring,
        earnings=EarningsAggregate.from_rows([(11, 3, 780)]),
        news=tuple(
            NewsItem(news_id=i, ts_ms=T0 + i, level="info", text=f"n{i}")
            for i in range(1, news + 1)
        ),
        market_events=(ActiveEvent(1, "crash", DRINKS, T0, T0 + 30_000),),
        quote_grace_versions=2,
        candle_interval_ms=60_000,
    )
    return MarketHolder.from_rehydrated(
        run, engine=cast(AsyncEngine, None), clock=FakeClock(T0), sink=lambda events: None
    )


def _publish(events: list[DomainEvent], holder: MarketHolder | None = None) -> list[dict[str, Any]]:
    async def scenario() -> list[str]:
        clock = FakeClock(T0 + 5_000)
        hub = Hub(clock=clock, replay_window_ms=60_000)
        socket = RecordingSocket()
        hub.connect(socket)
        publisher = Publisher(hub, seeded_book(holder or _holder()))
        publisher(events)
        for _ in range(100):
            await asyncio.sleep(0)
        return socket.frames

    return [json.loads(frame) for frame in asyncio.run(scenario())]


def _all_numbers_are_ints(value: Any, path: str = "") -> list[str]:
    if isinstance(value, float):
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _all_numbers_are_ints(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _all_numbers_are_ints(v, f"{path}[{i}]")]
    return []


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _later_tick(source: str, k: int) -> TickEntry:
    spec = _spec()
    last = _entries()[-1]
    state = initial_state(spec, now_ms=T0)
    state = advance(spec, state, now_ms=T0 + k * 1_000, run_seed=7).state
    return TickEntry(last.version + k, T0 + k * 1_000, source, tick_prices(spec, state, DRINKS))


def test_each_domain_event_yields_exactly_one_message_of_its_type() -> None:
    tick = _later_tick("tick", 5)
    order_entry = _later_tick("order", 6)
    item = NewsItem(news_id=9, ts_ms=T0, level="warning", text="Pas op")
    event = ActiveEvent(2, "bubble", DRINKS, T0 + 1_000, T0 + 31_000)
    frames = _publish(
        [
            TickCommitted(run_id=4, entry=tick),
            OrderCommitted(
                run_id=4,
                order_id=77,
                lines=(CommittedLine(11, 2, 260, 520),),
                total_cents=520,
                earnings_delta={11: DrinkEarnings(qty=2, revenue_cents=520)},
                entry=order_entry,
            ),
            NewsChanged(run_id=4, version=9, op="add", item=item),
            MarketEventStarted(run_id=4, version=10, event=event),
            MarketEventEnded(run_id=4, version=11, event=event),
        ]
    )

    assert [f["type"] for f in frames] == ["tick", "order", "news", "market_event", "market_event"]
    assert [f["seq"] for f in frames] == [1, 2, 3, 4, 5]
    assert [f["version"] for f in frames] == [tick.version, order_entry.version, 9, 10, 11]
    order = frames[1]["data"]
    assert order["order_id"] == 77 and order["total_cents"] == 520
    assert set(order["prices"]) == {"11", "12", "13"}  # PD12: every drink's new prices
    assert order["earnings_delta"] == {"11": {"qty": 2, "revenue_cents": 520}}
    assert frames[2]["data"] == {
        "op": "add",
        "item": {"news_id": 9, "ts_ms": T0, "level": "warning", "text": "Pas op"},
    }
    assert [f["data"]["op"] for f in frames[3:]] == ["start", "end"]
    assert frames[3]["data"]["t_end_ms"] == T0 + 31_000  # absolute (AC19)
    for frame in frames:
        Envelope.model_validate(frame)


def test_prices_are_integer_cents_on_the_two_tracks_and_the_charged_one_is_on_the_step() -> None:
    """AC23: no float anywhere; `price_cents` a multiple of the step."""
    frames = _publish([TickCommitted(run_id=4, entry=_later_tick("tick", 5))])

    assert _all_numbers_are_ints(frames) == []
    for drink in frames[0]["data"]["drinks"].values():
        assert drink["price_cents"] % STEP_CENTS == 0
        assert set(drink) == {"price_cents", "chart_price_cents", "candle"}


def test_the_tick_candle_continues_the_rings_bucket_and_a_gap_closes_it() -> None:
    """SD25: seeded from the ring, the tick's candle opens at the bucket's first price;
    after a `gap` the next tick opens a fresh candle in the same minute."""
    holder = _holder()
    first_chart = round(holder.ring[0].prices[11]["p_cont"] * 100)
    frames = _publish(
        [
            TickCommitted(run_id=4, entry=_later_tick("tick", 5)),
            TickCommitted(run_id=4, entry=_later_tick("gap", 6)),
            TickCommitted(run_id=4, entry=_later_tick("tick", 7)),
        ],
        holder,
    )

    candles = [f["data"]["drinks"]["11"]["candle"] for f in frames]
    charts = [f["data"]["drinks"]["11"]["chart_price_cents"] for f in frames]
    assert [f["data"]["candle_t_ms"] for f in frames] == [T0, T0, T0]
    assert candles[0][0] == first_chart  # open = the bucket's first tick, from the ring
    assert candles[1][0] == first_chart  # the gap tick still belongs to the open bucket
    assert candles[2] == [charts[2]] * 4  # the gap closed it: a fresh candle


def test_the_snapshot_carries_earnings_and_no_dead_fields() -> None:
    """AC20a."""
    data = snapshot(_holder(), tick_interval_ms=1_000)

    assert isinstance(data, Snapshot)
    dumped = data.model_dump(mode="json")
    assert dumped["earnings"] == {"11": {"qty": 3, "revenue_cents": 780}}
    assert not DEAD & _keys(dumped)
    assert _all_numbers_are_ints({k: v for k, v in dumped.items() if k != "params"}) == []
    assert [d["name"] for d in dumped["drinks"]] == ["Bier", "Wijn", "Fris"]
    assert dumped["run"] == {
        "run_id": 4,
        "tick_interval_ms": 1_000,
        "candle_interval_ms": 60_000,
        "quote_grace_versions": 2,
    }
    assert dumped["market_events"][0]["t_end_ms"] == T0 + 30_000
    assert set(dumped["bars"]) == {"11", "12", "13"}
    assert len(dumped["bars"]["11"]) == 1  # four ring ticks, one minute bucket


def test_the_snapshot_prices_are_the_latest_committed_tick() -> None:
    holder = _holder()
    latest = holder.ring[-1]
    data = snapshot(holder, tick_interval_ms=1_000)

    assert data is not None
    assert data.prices[11].price_cents == round(latest.prices[11]["p_q"] * 100)
    assert data.prices[11].chart_price_cents == round(latest.prices[11]["p_cont"] * 100)


def test_the_snapshot_holds_the_fifty_newest_news_items_newest_first() -> None:
    data = snapshot(_holder(news=60), tick_interval_ms=1_000)

    assert data is not None
    assert [n.news_id for n in data.news] == list(range(60, 10, -1))


def test_no_snapshot_without_a_live_run() -> None:
    holder = MarketHolder.empty(
        engine=cast(AsyncEngine, None), clock=FakeClock(T0), sink=lambda e: None
    )

    assert snapshot(holder, tick_interval_ms=1_000) is None


def test_the_snapshot_reads_nothing_but_memory() -> None:
    """The holder's engine is `None` here; any database read would fail."""
    assert snapshot(_holder(), tick_interval_ms=1_000) is not None

"""Domain events to closed messages to the hub; and the snapshot (Phase 3 SD24-SD26, SD28).

`Publisher` is the holder's sink (plan PD11): the only place that knows both the
domain events (`app/runtime/holder.py`) and the wire messages
(`app/realtime/messages.py`). The holder calls it after releasing its lock, and
it only builds frames and enqueues them -- `Hub.broadcast` never awaits (SD29).

- `TickCommitted` -> `tick`: every drink's two price tracks and the current
  candle from the `CandleBook` (SD25). A `gap` tick closes the bucket.
- `OrderCommitted` -> `order`: lines, total, earnings delta and every drink's new
  prices (plan PD12). The order's tick also goes through the candle book, so
  incremental candles agree with the snapshot's `bars_from_ring`.
- `NewsChanged` -> `news`; `MarketEventStarted` / `MarketEventEnded` ->
  `market_event` with absolute times.

Every envelope carries the committed engine `version`.

`snapshot(holder, tick_interval_ms=...)` is shared by `GET /api/state` and `/ws`.
It is built purely from holder memory -- never the database, never the engine
(AC15) -- and is `None` when there is no live run (SD16).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from app.db.mapping import cents_from_quantised, params_to_json
from app.db.news import NewsItem
from app.realtime.hub import Hub
from app.realtime.messages import (
    Bar,
    DrinkInfo,
    DrinkPrice,
    EarningsData,
    Envelope,
    MarketEventData,
    MarketEventInfo,
    NewsData,
    NewsItemData,
    OrderData,
    OrderLineData,
    RunInfo,
    ServerData,
    ServerMessageType,
    Snapshot,
    TickData,
    TickDrink,
)
from app.runtime.candles import CandleBook, bars_from_ring, chart_cents
from app.runtime.history import TickEntry
from app.runtime.holder import (
    DomainEvent,
    MarketEventEnded,
    MarketEventStarted,
    MarketHolder,
    NewsChanged,
    OrderCommitted,
    TickCommitted,
)
from app.runtime.market_events import ActiveEvent

SNAPSHOT_NEWS = 50


def drink_prices(entry: TickEntry) -> dict[int, DrinkPrice]:
    """A committed tick's two price tracks per drink (SD24): charged and chart."""
    return {
        drink_id: DrinkPrice(
            price_cents=cents_from_quantised(p["p_q"]), chart_price_cents=chart_cents(p["p_cont"])
        )
        for drink_id, p in entry.prices.items()
    }


def _news_item(item: NewsItem) -> NewsItemData:
    return NewsItemData(news_id=item.news_id, ts_ms=item.ts_ms, level=item.level, text=item.text)


def _event_info(event: ActiveEvent) -> MarketEventInfo:
    return MarketEventInfo(
        event_id=event.event_id,
        kind=event.kind,
        drink_ids=event.drink_ids,
        t_start_ms=event.t_start_ms,
        t_end_ms=event.t_end_ms,
    )


def seeded_book(holder: MarketHolder) -> CandleBook:
    """A candle book that has seen the ring, so the first tick's candle is the bucket's."""
    book = CandleBook(holder.candle_interval_ms)
    for entry in holder.ring:
        book.update(entry.wall_ts_ms, entry.source, _chart(entry))
    return book


def _chart(entry: TickEntry) -> dict[int, int]:
    return {drink_id: chart_cents(p["p_cont"]) for drink_id, p in entry.prices.items()}


class Publisher:
    def __init__(self, hub: Hub, candle_book: CandleBook) -> None:
        self._hub = hub
        self._book = candle_book

    def __call__(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            self._publish(event)

    def _broadcast(
        self, kind: ServerMessageType, run_id: int, version: int, data: ServerData
    ) -> None:
        self._hub.broadcast(
            Envelope(
                type=kind,
                seq=0,  # the hub stamps the real one
                ts_ms=self._hub.clock.wall_ms(),
                run_id=run_id,
                version=version,
                data=data,
            )
        )

    def _publish(self, event: DomainEvent) -> None:
        if isinstance(event, TickCommitted):
            entry = event.entry
            candles = self._book.update(entry.wall_ts_ms, entry.source, _chart(entry))
            prices = drink_prices(entry)
            self._broadcast(
                "tick",
                event.run_id,
                entry.version,
                TickData(
                    candle_t_ms=next(iter(candles.values())).t_ms,
                    drinks={
                        d: TickDrink(
                            price_cents=p.price_cents,
                            chart_price_cents=p.chart_price_cents,
                            candle=(candles[d].o, candles[d].h, candles[d].l, candles[d].c),
                        )
                        for d, p in prices.items()
                    },
                ),
            )
        elif isinstance(event, OrderCommitted):
            entry = event.entry
            self._book.update(entry.wall_ts_ms, entry.source, _chart(entry))
            self._broadcast(
                "order",
                event.run_id,
                entry.version,
                OrderData(
                    order_id=event.order_id,
                    lines=[
                        OrderLineData(
                            drink_id=ln.drink_id,
                            qty=ln.qty,
                            unit_price_cents=ln.unit_price_cents,
                            line_total_cents=ln.line_total_cents,
                        )
                        for ln in event.lines
                    ],
                    total_cents=event.total_cents,
                    earnings_delta={
                        d: EarningsData(qty=e.qty, revenue_cents=e.revenue_cents)
                        for d, e in event.earnings_delta.items()
                    },
                    prices=drink_prices(entry),
                ),
            )
        elif isinstance(event, NewsChanged):
            self._broadcast(
                "news",
                event.run_id,
                event.version,
                NewsData(op=event.op, item=_news_item(event.item)),
            )
        else:
            op: Literal["start", "end"] = (
                "start" if isinstance(event, MarketEventStarted) else "end"
            )
            assert isinstance(event, MarketEventStarted | MarketEventEnded)
            info = _event_info(event.event)
            self._broadcast(
                "market_event",
                event.run_id,
                event.version,
                MarketEventData(op=op, **info.model_dump()),
            )


def snapshot(holder: MarketHolder, *, tick_interval_ms: int) -> Snapshot | None:
    """The client-visible market, from memory only; `None` with no live run."""
    if holder.is_empty or holder.ring == ():
        return None
    assert holder.run_id is not None and holder.spec is not None
    latest = holder.ring[-1]
    names: Mapping[int, str] = dict(zip(holder.drink_ids, holder.spec.names, strict=True))
    return Snapshot(
        run=RunInfo(
            run_id=holder.run_id,
            tick_interval_ms=tick_interval_ms,
            candle_interval_ms=holder.candle_interval_ms,
            quote_grace_versions=holder.quote_grace_versions,
        ),
        drinks=[DrinkInfo(drink_id=d, name=names[d]) for d in holder.drink_ids],
        params=params_to_json(holder.spec.params),
        prices=drink_prices(latest),
        bars={
            d: [Bar(t_ms=c.t_ms, o=c.o, h=c.h, l=c.l, c=c.c) for c in series]
            for d, series in bars_from_ring(holder.ring, holder.candle_interval_ms).items()
        },
        news=[_news_item(n) for n in reversed(holder.news[-SNAPSHOT_NEWS:])],
        earnings={
            d: EarningsData(qty=e.qty, revenue_cents=e.revenue_cents)
            for d, e in holder.earnings.items()
        },
        market_events=[_event_info(e) for e in holder.market_events],
    )

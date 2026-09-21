# Realtime protocol

The Pydantic models in `app/realtime/messages.py` **are** the contract. TypeScript types are
generated from the OpenAPI schema and a recorded fixture is parsed through Zod as the runtime
half; CI fails on drift.

## What is wrong with the v1 payload

One fat `state` message (`backend/api.py:750-774`) on every broadcast, containing:

- the **entire history array** for the retained window;
- the **full news list**, re-read from `news.json` on every build;
- the **full earnings summary**, re-read and re-aggregated from the xlsx on every build;
- five fields no client reads: `prices_cont`, `expected_demand`, `revenue_per_drink`, `t`,
  `server_time_wall`.

The worst offender is not history. It is **`earnings.series`** (`persistence.py:161`) —
**one entry per sale**, rebroadcast in full to every client every 12 seconds, growing
linearly all night. By the end of a busy borrel it dwarfs everything else.

Two caveats when slimming, both easy to get wrong:

- `revenue_per_drink` is **not** unread — `/financials` serves it (`api.py:296`).
- `prices_disp` **is** read (`koers.html:369`) for the candle chart, so the 0.01 display
  track must survive.

## Envelope

```
{ v, type, seq, ts_ms, run_id, version, data }
```

`seq` lets a client detect a dropped message and request a resync. Without it, a dropped
`tick` leaves a permanent gap in the client's bar array that nothing will ever repair. It
costs four bytes.

`ts_ms` on every message lets the client maintain a running clock-skew estimate, which is
what makes absolute end-timestamps usable.

## Server to client

| Type | Contents | When |
|---|---|---|
| `hello` | Server time, `run_id`, `tick_interval_ms`, protocol version, your role | On connect |
| `snapshot` | Drinks, client-relevant params, prices, the history window, recent news, earnings **aggregates only**, active market events, `version` | On connect, or on resync |
| `tick` | `version`, `ts_ms`, prices, display prices, and a **server-bucketed bar**. ~200 bytes | 1 Hz |
| `order` | `order_id`, lines, `total_cents`, **earnings delta** | Per accepted order |
| `market_event` | `kind`, `drink_ids`, `t_start_ms`, **`t_end_ms`** | On start and end |
| `news` | `{op: add\|delete, item}` | On change |
| `config` | Params and drinks | On admin change |
| `theme` | The 21 tokens plus image references | On theme change |
| `resync` | "You are too far behind, or I restarted" | On backpressure overflow or version gap |

### Why `t_end_ms` matters

v1 sends only the event *type* while it is active (`api.py:773`), computed as
`now_ms() < _active_market_event["end_ms"]`. That is a boolean with no end time, so the
client cannot count down and only discovers the event ended on the **next scheduled
broadcast** — which means a 30-second crash overlay can linger for up to ten minutes.

With an absolute `t_end_ms`, the client subtracts its learned clock skew and runs its own
countdown and animation locally, with no polling.

## Client to server

| Type | Effect |
|---|---|
| `hello {last_version}` | Server replays missed ticks if they are still in the ring, otherwise sends a full `snapshot`. This makes reconnect cheap on venue wifi |
| `ping` | `pong`, as a **JSON frame** carrying server time |
| `resync_request` | Read-only. Returns a `snapshot` |

**Removed: the `"state"` message.** In v1 any connected browser tab can force a full engine
advance by sending the literal string `"state"` (`api.py:864`) — a trivial denial-of-service,
and one of the six uncontrolled entry points into time evolution. Its replacement is
read-only.

Also fixed: v1 replies to `ping` with the bare text `"pong"` mixed in among JSON frames
(`api.py:862`), so every client must string-check before `JSON.parse`.

## Name the price tracks

v1 has **three** and treats them as one:

| Track | Where produced | Who reads it |
|---|---|---|
| `prices_quant` — quantised to `step_quant` | `api.py:754` | ignored by the tiles |
| `history[].prices` | `engine.py:172` | the tiles (`koers.html:432`) |
| `history[].prices_disp` — quantised to 0.01 | `engine.py:173` | the candle charts (`koers.html:369`) |

History deduplicates on the *display* track (`engine.py:374`), so a tile can show a stale
quantised price while its chart has already moved. And `bar.html:356` falls back to
`history[last].ts` as a version token, which therefore freezes entirely during a flat period.

**v2 names exactly one "price shown to humans" and one "price used for charting",** and the
price charged is the `step_quant` track by assertion.

## Backpressure

`ConnectionManager.broadcast` (`api.py:254-267`) awaits each `send_text` serially. One slow
client — the big television on congested venue wifi — therefore stalls every other client and
the ticker behind it.

v2 gives each connection a bounded `asyncio.Queue` and a dedicated writer task. On overflow,
queued `tick`s are dropped and a `resync` is enqueued instead. **A slow consumer must never
be able to block the ticker.**

## Polling fallback

`GET /api/state` returns the same `snapshot` payload, read-only, with no engine advance. Both
`bar.html:369` and `koers.html` already rely on a polling fallback, and on venue wifi it is
cheap insurance. Unlike v1, calling it does not mutate anything.

## Bulk history

`GET /api/history?since=&bucket=` serves the full run, bucketed in SQL, for post-event
analysis. This is what keeps the live payload small while still allowing the whole evening to
be charted afterwards.

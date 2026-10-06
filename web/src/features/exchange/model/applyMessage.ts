/**
 * The message reducer: `(state, message) -> state`, pure -- no timers, no DOM,
 * no network (frontend-architecture.md, "State"). The WebSocket is the only
 * writer of live state, and every frame it delivers comes through here.
 *
 * **seq (AC18).** A broadcast applies only as the held `seq + 1`. One further
 * ahead means a frame was lost: `awaitingResync` is set (the client reads it to
 * send one `resync_request`) and nothing applies until a `snapshot`. Unicasts
 * -- `hello`, `snapshot`, `pong`, `error`, and the `theme` catch-up (PD7) --
 * carry the held seq without moving it. A `theme` is the exception to the gap
 * rule: it applies by revision (AC7) and never starts a resync, because with
 * no live run the server has no snapshot to end one. For the same reason it
 * applies during a resync too, without taking its seq: with no live run the
 * server answers the request with only the theme catch-up, and nothing would
 * ever end the resync for a theme waiting behind it.
 *
 * **boot (AC19, SD16).** A `hello` with a `boot_id` other than the held one
 * discards all live state and takes the hello's seq as the baseline; the
 * snapshot that follows rebuilds it. With the same `boot_id` the held seq
 * stays, because the server replays every broadcast after it.
 *
 * **Bars (SD3).** A `tick` carries each drink's current server-bucketed
 * candle: it replaces the last bar when the bucket matches and is appended
 * otherwise. An `order` carries prices but no candle, so it moves prices only;
 * the next tick carries the bucket the order changed. Nothing is synthesised.
 *
 * **Quote (Phase 5 SD2, PD1).** A `snapshot`, and an in-sequence `tick` or
 * `order`, each replace `quote` with one built from that message alone
 * (`quote.ts`), stamped with the `receivedAt` the caller passes in -- the
 * monotonic clock at receipt, so this stays pure. A dropped frame moves
 * nothing, and a new `boot_id` clears it until the next snapshot.
 */
import type {
  Bar,
  DrinkPrice,
  MarketEventInfo,
  NewsItem,
  RunInfo,
  ServerMessage,
  SnapshotData,
  ThemeData,
} from './schemas'
import { type Quote, quoteFromOrder, quoteFromSnapshot, quoteFromTick } from './quote'

type Of<K extends ServerMessage['type']> = Extract<ServerMessage, { type: K }>

export type Status = 'connecting' | 'open' | 'offline'
export type DrinkId = number

export interface ExchangeState {
  status: Status
  bootId: string | null
  /** The last applied seq; `null` before any baseline. */
  seq: number | null
  awaitingResync: boolean
  /** No live run: `hello.run_id` was null, or the state poll said so. */
  empty: boolean
  theme: ThemeData | null
  /** Server time minus client time, ms (SD18); written by the client. */
  skewOffsetMs: number
  run: RunInfo | null
  drinks: { drink_id: DrinkId; name: string }[]
  prices: Record<DrinkId, DrinkPrice>
  /** The `price_cents` displayed before the last price change, for pulses (SD23). */
  prevPriceCents: Record<DrinkId, number>
  bars: Record<DrinkId, Bar[]>
  /** Newest first, as the snapshot sends it. */
  news: NewsItem[]
  marketEvents: MarketEventInfo[]
  /** Bumped by every snapshot, so a chart knows when to `setData` again. */
  snapshotGen: number
  /** The latest quote: one message's version and prices (Phase 5 SD2). */
  quote: Quote | null
}

export const NEWS_LIMIT = 50

export const initialState: ExchangeState = {
  status: 'connecting',
  bootId: null,
  seq: null,
  awaitingResync: false,
  empty: false,
  theme: null,
  skewOffsetMs: 0,
  run: null,
  drinks: [],
  prices: {},
  prevPriceCents: {},
  bars: {},
  news: [],
  marketEvents: [],
  snapshotGen: 0,
  quote: null,
}

const UNICAST: ReadonlySet<ServerMessage['type']> = new Set(['hello', 'snapshot', 'pong', 'error'])

export function applyMessage(
  state: ExchangeState,
  message: ServerMessage,
  receivedAt: number,
): ExchangeState {
  if (message.type === 'hello') return applyHello(state, message)
  if (message.type === 'snapshot') {
    return applySnapshot(state, message.seq, message.data, receivedAt)
  }
  if (message.type === 'resync') return { ...state, awaitingResync: true }
  if (state.seq === null) return state
  if (message.type === 'theme') {
    // Ordered by revision, not seq, so it never starts or waits on a resync: with
    // no live run there is no snapshot to end one (PD7). It still takes its seq
    // when next in line and no resync is pending.
    const next = applyTheme(state, message.data)
    const inLine = !state.awaitingResync && message.seq === state.seq + 1
    return inLine ? { ...next, seq: message.seq } : next
  }
  if (state.awaitingResync) return state
  if (message.seq === state.seq) {
    return UNICAST.has(message.type) ? applyBroadcast(state, message, receivedAt) : state
  }
  if (message.seq > state.seq + 1) return { ...state, awaitingResync: true }
  if (message.seq < state.seq) return state
  return { ...applyBroadcast(state, message, receivedAt), seq: message.seq }
}

function applyBroadcast(
  state: ExchangeState,
  message: ServerMessage,
  receivedAt: number,
): ExchangeState {
  switch (message.type) {
    case 'tick': {
      const next = applyTick(state, message)
      return { ...next, quote: quoteFromTick(message, receivedAt) ?? state.quote }
    }
    case 'order': {
      const next = applyPrices(state, message.data.prices)
      return { ...next, quote: quoteFromOrder(message, receivedAt) ?? state.quote }
    }
    case 'market_event':
      return applyMarketEvent(state, message)
    case 'news':
      return applyNews(state, message)
    case 'pong':
    case 'error':
      return state
    case 'hello':
    case 'snapshot':
    case 'resync':
    case 'theme':
      return state // handled before seq, in applyMessage
    default: {
      const unreachable: never = message
      return unreachable
    }
  }
}

function applyHello(state: ExchangeState, message: Of<'hello'>): ExchangeState {
  const { boot_id, run_id, theme } = message.data
  const base =
    boot_id === state.bootId
      ? state
      : {
          ...initialState,
          status: state.status,
          theme: state.theme,
          skewOffsetMs: state.skewOffsetMs,
          bootId: boot_id,
          seq: message.seq,
        }
  return applyTheme({ ...base, awaitingResync: false, empty: run_id === null }, theme)
}

/**
 * A `GET /api/state` result while offline (SD17): a snapshot with no seq, so
 * the held seq stays. The client then reconnects with no `boot_id`, so the
 * server sends a snapshot rather than replaying older frames over it.
 */
export function applyPolledState(
  state: ExchangeState,
  data: SnapshotData,
  receivedAt: number,
): ExchangeState {
  return applySnapshot(state, state.seq, data, receivedAt)
}

/** A poll's 409 `no_live_run` (SD17). */
export function applyNoLiveRun(state: ExchangeState): ExchangeState {
  return state.empty ? state : { ...state, empty: true }
}

function applySnapshot(
  state: ExchangeState,
  seq: number | null,
  data: SnapshotData,
  receivedAt: number,
): ExchangeState {
  const prices = keyed(data.prices)
  const prevPriceCents: Record<DrinkId, number> = {}
  for (const [id, price] of Object.entries(prices)) prevPriceCents[Number(id)] = price.price_cents
  return {
    ...state,
    seq,
    awaitingResync: false,
    empty: false,
    run: data.run,
    drinks: data.drinks,
    prices,
    prevPriceCents,
    bars: keyed(data.bars),
    news: data.news,
    marketEvents: data.market_events,
    snapshotGen: state.snapshotGen + 1,
    quote: quoteFromSnapshot(data, receivedAt),
  }
}

function applyTick(state: ExchangeState, message: Of<'tick'>): ExchangeState {
  const { candle_t_ms, drinks } = message.data
  const prices: Record<DrinkId, DrinkPrice> = {}
  const bars = { ...state.bars }
  for (const [key, drink] of Object.entries(drinks)) {
    const id = Number(key)
    const [o, h, l, c] = drink.candle
    prices[id] = { price_cents: drink.price_cents, chart_price_cents: drink.chart_price_cents }
    bars[id] = withBar(bars[id] ?? [], { t_ms: candle_t_ms, o, h, l, c })
  }
  return { ...applyPrices(state, prices), bars }
}

function withBar(series: Bar[], bar: Bar): Bar[] {
  const last = series.at(-1)
  if (last === undefined || bar.t_ms > last.t_ms) return [...series, bar]
  if (bar.t_ms === last.t_ms) return [...series.slice(0, -1), bar]
  return series // an older bucket than the last held: the server never sends one
}

function applyPrices(
  state: ExchangeState,
  update: Record<string | number, DrinkPrice>,
): ExchangeState {
  const prices = { ...state.prices }
  const prevPriceCents = { ...state.prevPriceCents }
  for (const [key, price] of Object.entries(update)) {
    const id = Number(key)
    prevPriceCents[id] = state.prices[id]?.price_cents ?? price.price_cents
    prices[id] = price
  }
  return { ...state, prices, prevPriceCents }
}

function applyMarketEvent(state: ExchangeState, message: Of<'market_event'>): ExchangeState {
  const { op, ...event } = message.data
  const held = state.marketEvents.some((e) => e.event_id === event.event_id)
  if (op === 'start') {
    return held ? state : { ...state, marketEvents: [...state.marketEvents, event] }
  }
  if (!held) return state // a late end
  return { ...state, marketEvents: state.marketEvents.filter((e) => e.event_id !== event.event_id) }
}

function applyNews(state: ExchangeState, message: Of<'news'>): ExchangeState {
  const { op, item } = message.data
  const rest = state.news.filter((n) => n.news_id !== item.news_id)
  return { ...state, news: op === 'add' ? [item, ...rest].slice(0, NEWS_LIMIT) : rest }
}

function applyTheme(state: ExchangeState, theme: ThemeData): ExchangeState {
  if (state.theme !== null && theme.revision <= state.theme.revision) return state
  return { ...state, theme }
}

function keyed<T>(record: Record<string, T>): Record<DrinkId, T> {
  const out: Record<DrinkId, T> = {}
  for (const [key, value] of Object.entries(record)) out[Number(key)] = value
  return out
}

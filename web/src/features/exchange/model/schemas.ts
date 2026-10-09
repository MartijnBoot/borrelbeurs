/**
 * The realtime protocol at the client's boundary: one Zod schema per message
 * (SD26), mirroring `app/realtime/messages.py` field for field.
 *
 * Every object is strict, as the server's models are `extra="forbid"`: a
 * field on one side and not the other fails `schemas.test.ts` against the
 * recorded fixture rather than slipping through. Prices are integer cents,
 * never floats (`StrictInt` on the server). JSON object keys are strings, so
 * the server's `dict[int, …]` maps arrive keyed by the drink id as a string.
 */
import { z } from 'zod'

const Int = z.int()
const NonNegative = z.int().nonnegative()
/** A `dict[int, …]` key: a drink id, as JSON writes it. */
const IdKey = z.string().regex(/^-?\d+$/)

const NewsLevel = z.enum(['info', 'success', 'warning', 'danger'])
const EventKind = z.enum(['crash', 'bubble', 'correction'])
const Role = z.enum(['display', 'bar', 'admin'])
const PresetName = z.enum(['oudgeld', 'blauw', 'groen', 'paars', 'rood', 'custom'])

// --- prices and candles --------------------------------------------------------

export const DrinkPrice = z.strictObject({
  price_cents: NonNegative,
  chart_price_cents: NonNegative,
})

const TickDrink = z.strictObject({
  price_cents: NonNegative,
  chart_price_cents: NonNegative,
  // The current bucket's [open, high, low, close] on chart_price_cents.
  candle: z.tuple([Int, Int, Int, Int]),
})

export const Bar = z.strictObject({ t_ms: Int, o: Int, h: Int, l: Int, c: Int })

// --- server -> client data -----------------------------------------------------

export const TickData = z.strictObject({
  candle_t_ms: Int,
  drinks: z.record(IdKey, TickDrink),
})

export const RunInfo = z.strictObject({
  run_id: Int,
  tick_interval_ms: Int,
  candle_interval_ms: Int,
  quote_grace_versions: NonNegative,
})

/** `active` is false once removed from a live run (Phase 6 SD13): listed, never priced. */
const DrinkInfo = z.strictObject({ drink_id: Int, name: z.string(), active: z.boolean() })

const ConfigRunInfo = RunInfo.extend({ name: z.string() })

export const NewsItem = z.strictObject({
  news_id: Int,
  ts_ms: Int,
  level: NewsLevel,
  text: z.string(),
})

export const DrinkEarnings = z.strictObject({ qty: NonNegative, revenue_cents: NonNegative })

export const MarketEventInfo = z.strictObject({
  event_id: Int,
  kind: EventKind,
  drink_ids: z.array(Int),
  t_start_ms: Int,
  t_end_ms: Int,
})

const Params = z.record(z.string(), z.json())

export const SnapshotData = z.strictObject({
  version: Int,
  run: RunInfo,
  drinks: z.array(DrinkInfo),
  params: Params,
  prices: z.record(IdKey, DrinkPrice),
  bars: z.record(IdKey, z.array(Bar)),
  news: z.array(NewsItem).max(50),
  earnings: z.record(IdKey, DrinkEarnings),
  market_events: z.array(MarketEventInfo),
})

const OrderLine = z.strictObject({
  drink_id: Int,
  qty: z.int().min(1),
  unit_price_cents: NonNegative,
  line_total_cents: NonNegative,
})

export const OrderData = z.strictObject({
  order_id: Int,
  lines: z.array(OrderLine),
  total_cents: NonNegative,
  earnings_delta: z.record(IdKey, DrinkEarnings),
  prices: z.record(IdKey, DrinkPrice),
})

export const MarketEventData = z.strictObject({
  op: z.enum(['start', 'end']),
  event_id: Int,
  kind: EventKind,
  drink_ids: z.array(Int),
  t_start_ms: Int,
  t_end_ms: Int,
})

/** A committed live config change (Phase 6 SD18). */
export const ConfigData = z.strictObject({
  revision: NonNegative,
  run: ConfigRunInfo,
  drinks: z.array(DrinkInfo),
  params: Params,
})

export const NewsData = z.strictObject({ op: z.enum(['add', 'delete']), item: NewsItem })

/** The active theme (PD3): every manifest token, name -> CSS value, and the font stack. */
export const ThemeData = z.strictObject({
  preset: PresetName,
  revision: NonNegative,
  tokens: z.record(z.string(), z.string()),
  font_family: z.string(),
  /** Each image slot as `/assets/<id>`, or null (Phase 6 PD9). */
  images: z.strictObject({
    bg: z.string().nullable(),
    header: z.string().nullable(),
    logo: z.string().nullable(),
    promo: z.string().nullable(),
  }),
})

export const HelloData = z.strictObject({
  boot_id: z.string(),
  run_id: Int.nullable(),
  tick_interval_ms: Int,
  protocol: Int,
  role: Role,
  theme: ThemeData,
})

/** The live run was closed (Phase 7 SD2): the market is empty from here on. */
export const RunClosedData = z.strictObject({ run_id: Int, name: z.string(), ended_at_ms: Int })

const PongData = z.strictObject({ server_ts_ms: Int })
const ResyncData = z.strictObject({})
const ErrorData = z.strictObject({ code: z.string() })

// --- the envelope ----------------------------------------------------------------

function envelope<const T extends string, D extends z.ZodType>(type: T, data: D) {
  return z.strictObject({
    v: z.literal(1),
    type: z.literal(type),
    seq: NonNegative,
    ts_ms: Int,
    run_id: Int.nullable(),
    version: NonNegative.nullable(),
    data,
  })
}

/** `{v, type, seq, ts_ms, run_id, version, data}`, discriminated on `type`. */
export const ServerMessage = z.discriminatedUnion('type', [
  envelope('hello', HelloData),
  envelope('snapshot', SnapshotData),
  envelope('tick', TickData),
  envelope('order', OrderData),
  envelope('market_event', MarketEventData),
  envelope('news', NewsData),
  envelope('pong', PongData),
  envelope('resync', ResyncData),
  envelope('error', ErrorData),
  envelope('theme', ThemeData),
  envelope('config', ConfigData),
  envelope('run_closed', RunClosedData),
])

export type ServerMessage = z.infer<typeof ServerMessage>
export type ServerMessageType = ServerMessage['type']

export const SERVER_MESSAGE_TYPES: readonly ServerMessageType[] = ServerMessage.options.map(
  (option) => option.shape.type.value,
)

// --- client -> server ------------------------------------------------------------

export const ClientMessage = z.discriminatedUnion('type', [
  z.strictObject({ type: z.literal('hello'), boot_id: z.string(), last_seq: NonNegative }),
  z.strictObject({ type: z.literal('ping') }),
  z.strictObject({ type: z.literal('resync_request') }),
])

export type ClientMessage = z.infer<typeof ClientMessage>

export type DrinkPrice = z.infer<typeof DrinkPrice>
export type DrinkEarnings = z.infer<typeof DrinkEarnings>
export type Bar = z.infer<typeof Bar>
export type RunInfo = z.infer<typeof RunInfo>
export type DrinkInfo = z.infer<typeof DrinkInfo>
export type NewsItem = z.infer<typeof NewsItem>
export type MarketEventInfo = z.infer<typeof MarketEventInfo>
export type SnapshotData = z.infer<typeof SnapshotData>
export type ConfigData = z.infer<typeof ConfigData>
export type ThemeData = z.infer<typeof ThemeData>

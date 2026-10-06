/**
 * The `Quote`: one version and the prices that belong to it, from **one**
 * server message (Phase 5 SD2, AC2; D-05).
 *
 * v1 sent a version from the latest message with prices from the one on
 * screen (`bar.html:220`, `:353-357`). Here the pair cannot come apart: a
 * `Quote` is frozen, carries a `unique symbol` brand only this module can
 * write, and each builder takes a single message or 409 body. A hand-built
 * object is a type error, and `quote.provenance.test.ts` fails on a cast to
 * `Quote` anywhere else, or a builder called from anywhere but the reducer and
 * the order intents.
 *
 * `prices` holds `price_cents` -- the charged track, never `chart_price_cents`
 * -- keyed by `drink_id`. `receivedAt` is the client's monotonic clock at
 * receipt, passed in so the reducer stays pure (PD1). A tick or order whose
 * envelope has no `version` yields no quote (PD4): it cannot be honoured.
 */
import type { DrinkId } from './applyMessage'
import type { ServerMessage, SnapshotData } from './schemas'

declare const brand: unique symbol

export interface Quote {
  readonly version: number
  readonly prices: Readonly<Record<DrinkId, number>>
  /** `performance.now()` when the message arrived. */
  readonly receivedAt: number
  readonly [brand]: true
}

/** A 409 `price_changed` body: the live `version` and every line's `price_cents`. */
export interface PriceChanged {
  readonly version: number
  readonly prices: readonly { readonly drink_id: number; readonly price_cents: number }[]
}

type Of<K extends ServerMessage['type']> = Extract<ServerMessage, { type: K }>

function freeze(version: number, prices: Record<DrinkId, number>, receivedAt: number): Quote {
  return Object.freeze({ version, prices: Object.freeze(prices), receivedAt }) as Quote
}

function priceCents(record: Record<string, { price_cents: number }>): Record<DrinkId, number> {
  const prices: Record<DrinkId, number> = {}
  for (const [id, price] of Object.entries(record)) prices[Number(id)] = price.price_cents
  return prices
}

export function quoteFromSnapshot(data: SnapshotData, receivedAt: number): Quote {
  return freeze(data.version, priceCents(data.prices), receivedAt)
}

export function quoteFromTick(message: Of<'tick'>, receivedAt: number): Quote | null {
  if (message.version === null) return null
  return freeze(message.version, priceCents(message.data.drinks), receivedAt)
}

export function quoteFromOrder(message: Of<'order'>, receivedAt: number): Quote | null {
  if (message.version === null) return null
  return freeze(message.version, priceCents(message.data.prices), receivedAt)
}

export function quoteFromPriceChanged(body: PriceChanged, receivedAt: number): Quote {
  const prices: Record<DrinkId, number> = {}
  for (const line of body.prices) prices[line.drink_id] = line.price_cents
  return freeze(body.version, prices, receivedAt)
}

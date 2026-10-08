/**
 * The order-intent machine (Phase 5 SD5-SD10): one entry per tap, from send
 * to a settled state, timer- and transport-injected so it runs under fake
 * timers.
 *
 * - `create(quote, drinkId)` builds the body from that one `Quote`, freezes
 *   it, takes a fresh key and sends at once (SD5-SD7). The same frozen body
 *   object is posted on every attempt, so every retry serialises it to the
 *   same bytes.
 * - A network error, a timeout or a 503 retries after 1, 2 and 4 s with the
 *   same key and body; then the entry is `unknown` (SD8). `retry()` makes one
 *   more attempt, with no automatic retries behind it (PD11).
 * - A 409 promotes the displayed quote on arrival (PD9) and queues a conflict
 *   holding the 409's own version and price, built by `quoteFromPriceChanged`
 *   (SD9). Conflicts surface one at a time, in tap order (AC14). `confirm()`
 *   re-sends the head with a new key from exactly that record; `cancel()`
 *   sends nothing.
 * - A 2xx is `accepted` with the receipt's price (AC3) and promotes. A 401
 *   leaves the entry in flight: `lib/http` sends the page to login (SD12).
 *   A 422 `drink_unavailable` (a drink removed from the run, Phase 6 SD13) is
 *   `unavailable`; any other answer -- a 422 above all -- is `failed`. Neither
 *   is retried.
 *
 * Settled entries linger `LINGER_MS`, then go; `unknown` stays until
 * "Opnieuw" or "Sluiten" (PD7). Nothing here touches the store (SD10).
 */
import { HttpError } from '../../../lib/http'
import { quoteFromPriceChanged, type DrinkId, type Quote } from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'

/** SD8: the waits before the first, second and third automatic retry. */
export const RETRY_DELAYS_MS: readonly number[] = [1000, 2000, 4000]
/** PD7: how long an accepted, failed, cancelled or dismissed entry stays shown. */
export const LINGER_MS = 3000

export type EntryState =
  | 'sending'
  | 'accepted'
  | 'unknown'
  | 'failed'
  | 'unavailable'
  | 'conflict'
  | 'cancelled'
  | 'dismissed'

export interface OrderEntry {
  readonly id: number
  /** Tap order: conflicts surface by it (AC14); a confirmation keeps its tap's. */
  readonly tap: number
  readonly drinkId: DrinkId
  readonly key: string
  readonly body: OrderBody
  readonly state: EntryState
  /** The receipt's `unit_price_cents`, once accepted (AC3). */
  readonly unitPriceCents: number | null
  /** The 409's record, while the entry is a conflict (SD9). */
  readonly conflict: Quote | null
}

export interface Conflict {
  readonly id: number
  readonly drinkId: DrinkId
  readonly quote: Quote
}

export interface OrderIntentsDeps<Id = unknown> {
  post(request: { key: string; body: OrderBody }): Promise<OrderOutcome>
  uuid(): string
  /** The monotonic clock, to stamp a 409's record as it arrives. */
  now(): number
  setTimeout(fn: () => void, ms: number): Id
  clearTimeout(id: Id): void
  onChange(): void
  /** A 2xx or a 409 arrived: the displayed quote becomes the latest (SD3). */
  onPromote(): void
}

export interface OrderIntents {
  /** In tap order; a new array on every change. */
  readonly entries: readonly OrderEntry[]
  readonly headConflict: Conflict | null
  /** The new entry's id, or `null` when the quote has no price for the drink. */
  create(quote: Quote, drinkId: DrinkId): number | null
  retry(id: number): void
  dismiss(id: number): void
  confirm(): void
  cancel(): void
  dispose(): void
}

interface Intent<Id> {
  entry: OrderEntry
  retries: number
  timer: Id | null
}

function bodyFor(quote: Quote, drinkId: DrinkId): OrderBody | null {
  const price = quote.prices[drinkId]
  if (price === undefined) return null
  const line = Object.freeze({ drink_id: drinkId, qty: 1, unit_price_cents: price })
  return Object.freeze({ quote_version: quote.version, lines: Object.freeze([line]) })
}

function retryable(error: unknown): boolean {
  // Not an HTTP answer: a network failure or a timeout's abort.
  if (!(error instanceof HttpError)) return true
  // A 5xx, or a 2xx whose body could not be read: the order may have been
  // booked, so ask again with the same key -- the server replays the receipt.
  return error.status >= 500 || (error.status < 300 && error.code === 'invalid_response')
}

export function createOrderIntents<Id>(deps: OrderIntentsDeps<Id>): OrderIntents {
  const intents = new Map<number, Intent<Id>>()
  let entries: readonly OrderEntry[] = []
  let headConflict: Conflict | null = null
  let nextId = 1
  let nextTap = 1
  let disposed = false

  function publish() {
    entries = [...intents.values()].map((i) => i.entry).sort((a, b) => a.tap - b.tap)
    const head = entries.find((e) => e.state === 'conflict')
    headConflict =
      head?.conflict == null ? null : { id: head.id, drinkId: head.drinkId, quote: head.conflict }
    deps.onChange()
  }

  function set(intent: Intent<Id>, patch: Partial<OrderEntry>) {
    intent.entry = Object.freeze({ ...intent.entry, ...patch })
  }

  function clearTimer(intent: Intent<Id>) {
    if (intent.timer !== null) deps.clearTimeout(intent.timer)
    intent.timer = null
  }

  function linger(intent: Intent<Id>) {
    clearTimer(intent)
    intent.timer = deps.setTimeout(() => {
      intents.delete(intent.entry.id)
      publish()
    }, LINGER_MS)
  }

  /** The answer belongs to the attempt still in flight for this intent. */
  function current(intent: Intent<Id>, key: string): boolean {
    return (
      !disposed &&
      intents.get(intent.entry.id) === intent &&
      intent.entry.key === key &&
      intent.entry.state === 'sending'
    )
  }

  function send(intent: Intent<Id>, automatic: boolean) {
    const { key, body } = intent.entry
    set(intent, { state: 'sending' })
    deps.post({ key, body }).then(
      (outcome) => answered(intent, key, outcome),
      (error: unknown) => failed(intent, key, error, automatic),
    )
  }

  function answered(intent: Intent<Id>, key: string, outcome: OrderOutcome) {
    if (!current(intent, key)) return
    const { drinkId } = intent.entry
    if (outcome.kind === 'accepted') {
      const line = outcome.receipt.lines.find((l) => l.drink_id === drinkId)
      set(intent, { state: 'accepted', unitPriceCents: line?.unit_price_cents ?? null })
      linger(intent)
    } else {
      const record = quoteFromPriceChanged(outcome.body, deps.now())
      if (record.prices[drinkId] === undefined) {
        // The server sends every line's price; without one there is nothing to confirm.
        set(intent, { state: 'failed' })
        linger(intent)
      } else {
        set(intent, { state: 'conflict', conflict: record })
      }
    }
    publish()
    deps.onPromote()
  }

  function failed(intent: Intent<Id>, key: string, error: unknown, automatic: boolean) {
    if (!current(intent, key)) return
    if (retryable(error)) {
      if (automatic && intent.retries < RETRY_DELAYS_MS.length) {
        intent.timer = deps.setTimeout(() => {
          intent.timer = null
          intent.retries += 1
          send(intent, true)
        }, RETRY_DELAYS_MS[intent.retries])
        return
      }
      set(intent, { state: 'unknown' })
    } else if (error instanceof HttpError && error.status === 401) {
      return // lib/http has sent the page to login (SD12)
    } else if (error instanceof HttpError && error.code === 'drink_unavailable') {
      set(intent, { state: 'unavailable' })
      linger(intent)
    } else {
      set(intent, { state: 'failed' })
      linger(intent)
    }
    publish()
  }

  function head(): Intent<Id> | undefined {
    return headConflict === null ? undefined : intents.get(headConflict.id)
  }

  return {
    get entries() {
      return entries
    },
    get headConflict() {
      return headConflict
    },
    create(quote, drinkId) {
      const body = bodyFor(quote, drinkId)
      if (body === null || disposed) return null
      const id = nextId++
      const intent: Intent<Id> = {
        entry: Object.freeze({
          id,
          tap: nextTap++,
          drinkId,
          key: deps.uuid(),
          body,
          state: 'sending',
          unitPriceCents: null,
          conflict: null,
        }),
        retries: 0,
        timer: null,
      }
      intents.set(id, intent)
      send(intent, true)
      publish()
      return id
    },
    retry(id) {
      const intent = intents.get(id)
      if (intent?.entry.state !== 'unknown') return
      send(intent, false)
      publish()
    },
    dismiss(id) {
      const intent = intents.get(id)
      if (intent?.entry.state !== 'unknown') return
      set(intent, { state: 'dismissed' })
      linger(intent)
      publish()
    },
    confirm() {
      const intent = head()
      const record = intent?.entry.conflict
      if (intent === undefined || record == null) return
      const body = bodyFor(record, intent.entry.drinkId)
      if (body === null) return
      set(intent, { key: deps.uuid(), body, conflict: null })
      intent.retries = 0
      send(intent, true)
      publish()
    },
    cancel() {
      const intent = head()
      if (intent === undefined) return
      set(intent, { state: 'cancelled', conflict: null })
      linger(intent)
      publish()
    },
    dispose() {
      disposed = true
      for (const intent of intents.values()) clearTimer(intent)
    },
  }
}

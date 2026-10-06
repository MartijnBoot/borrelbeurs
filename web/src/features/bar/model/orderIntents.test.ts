// The order-intent machine on fake timers with a scripted transport
// (Phase 5 T7): SD5-SD10, PD7, PD9, PD11.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '../../../lib/http'
import { quoteFromPriceChanged, type Quote } from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { createOrderIntents, LINGER_MS, RETRY_DELAYS_MS, type OrderIntents } from './orderIntents'

interface Call {
  key: string
  body: OrderBody
  text: string
  resolve(outcome: OrderOutcome): void
  reject(error: unknown): void
}

function quote(version: number, prices: Record<number, number>, receivedAt = 0): Quote {
  const lines = Object.entries(prices).map(([id, cents]) => ({
    drink_id: Number(id),
    price_cents: cents,
  }))
  return quoteFromPriceChanged({ version, prices: lines }, receivedAt)
}

function accepted(body: OrderBody, unitPriceCents = body.lines[0].unit_price_cents): OrderOutcome {
  const { drink_id } = body.lines[0]
  return {
    kind: 'accepted',
    receipt: {
      order_id: 1,
      version: body.quote_version + 1,
      wall_ts_ms: 0,
      quote_version: body.quote_version,
      lines: [
        { drink_id, qty: 1, unit_price_cents: unitPriceCents, line_total_cents: unitPriceCents },
      ],
      total_cents: unitPriceCents,
    },
  }
}

function priceChanged(version: number, drinkId: number, cents: number): OrderOutcome {
  return {
    kind: 'price_changed',
    body: { version, prices: [{ drink_id: drinkId, price_cents: cents }] },
  }
}

const unavailable = () => new HttpError(503, 'persistence_unavailable', 'down')
const network = () => new TypeError('Failed to fetch')
const timeout = () => new DOMException('signal timed out', 'TimeoutError')

let calls: Call[]
let promotes: number
let intents: OrderIntents
let keys: number

beforeEach(() => {
  vi.useFakeTimers()
  calls = []
  promotes = 0
  keys = 0
  intents = createOrderIntents({
    post: ({ key, body }) =>
      new Promise<OrderOutcome>((resolve, reject) => {
        calls.push({ key, body, text: JSON.stringify(body), resolve, reject })
      }),
    uuid: () => `key-${String(++keys).padStart(4, '0')}`,
    now: () => 0,
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    onChange: () => {},
    onPromote: () => promotes++,
  })
})

afterEach(() => {
  intents.dispose()
  vi.useRealTimers()
})

const settle = () => vi.advanceTimersByTimeAsync(0)
const Q = quote(7, { 1: 250, 2: 300 })

describe('create', () => {
  it('posts one line of qty 1 at the quote version and price, frozen', () => {
    intents.create(Q, 1)
    expect(calls).toHaveLength(1)
    expect(calls[0].body).toEqual({
      quote_version: 7,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }],
    })
    expect(Object.isFrozen(calls[0].body)).toBe(true)
    expect(Object.isFrozen(calls[0].body.lines[0])).toBe(true)
    expect(intents.entries[0]).toMatchObject({ drinkId: 1, state: 'sending' })
  })

  it('two creates within 100 ms on one drink post twice with distinct keys (AC9)', () => {
    intents.create(Q, 1)
    vi.advanceTimersByTime(50)
    intents.create(Q, 1)
    expect(calls.map((c) => c.key)).toEqual(['key-0001', 'key-0002'])
  })

  it('a drink missing from the quote creates nothing', () => {
    expect(intents.create(Q, 99)).toBeNull()
    expect(calls).toHaveLength(0)
  })
})

describe('success', () => {
  it('a 2xx is accepted with the receipt price, promotes, and lingers 3 s (AC3, PD7)', async () => {
    intents.create(Q, 1)
    calls[0].resolve(accepted(calls[0].body, 260))
    await settle()
    expect(intents.entries[0]).toMatchObject({ state: 'accepted', unitPriceCents: 260 })
    expect(promotes).toBe(1)
    await vi.advanceTimersByTimeAsync(LINGER_MS - 1)
    expect(intents.entries).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(intents.entries).toHaveLength(0)
  })
})

describe('retries (SD8)', () => {
  it('network, timeout and 503 retry at +1, +2, +4 s with the same key and body; then unknown (AC10, AC11)', async () => {
    expect(RETRY_DELAYS_MS).toEqual([1000, 2000, 4000])
    intents.create(Q, 1)
    const failures = [network(), timeout(), unavailable(), network()]
    for (const [i, failure] of failures.entries()) {
      calls[i].reject(failure)
      await settle()
      if (i === 3) break
      await vi.advanceTimersByTimeAsync(RETRY_DELAYS_MS[i] - 1)
      expect(calls).toHaveLength(i + 1)
      expect(intents.entries[0].state).toBe('sending')
      await vi.advanceTimersByTimeAsync(1)
      expect(calls).toHaveLength(i + 2)
    }
    expect(new Set(calls.map((c) => c.key))).toEqual(new Set(['key-0001']))
    expect(new Set(calls.map((c) => c.text)).size).toBe(1)
    expect(calls.every((c) => c.body === calls[0].body)).toBe(true)
    expect(intents.entries[0].state).toBe('unknown')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(4)
    expect(intents.entries[0].state).toBe('unknown') // stays until Opnieuw or Sluiten
  })

  it('a 503 then a 200 replay is one accepted entry (AC26)', async () => {
    intents.create(Q, 1)
    calls[0].reject(unavailable())
    await settle()
    await vi.advanceTimersByTimeAsync(1000)
    calls[1].resolve(accepted(calls[1].body))
    await settle()
    expect(intents.entries).toHaveLength(1)
    expect(intents.entries[0]).toMatchObject({ state: 'accepted', unitPriceCents: 250 })
    expect(calls).toHaveLength(2)
  })

  async function toUnknown(): Promise<number> {
    const id = intents.create(Q, 1)!
    for (let i = 0; i < 4; i++) {
      calls[i].reject(network())
      await settle()
      if (i < 3) await vi.advanceTimersByTimeAsync(RETRY_DELAYS_MS[i])
    }
    return id
  }

  it('retry() sends the same key and body once; a failure returns it to unknown (PD11)', async () => {
    const id = await toUnknown()
    intents.retry(id)
    expect(calls).toHaveLength(5)
    expect(calls[4]).toMatchObject({ key: calls[0].key, text: calls[0].text })
    expect(intents.entries[0].state).toBe('sending')
    calls[4].reject(timeout())
    await settle()
    expect(intents.entries[0].state).toBe('unknown')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(5)
  })

  it('retry() resolving 200 is accepted', async () => {
    const id = await toUnknown()
    intents.retry(id)
    calls[4].resolve(accepted(calls[4].body))
    await settle()
    expect(intents.entries[0].state).toBe('accepted')
  })

  it('dismiss() shows "maybe booked" for 3 s, then removes it (PD7)', async () => {
    const id = await toUnknown()
    intents.dismiss(id)
    expect(intents.entries[0].state).toBe('dismissed')
    await vi.advanceTimersByTimeAsync(LINGER_MS)
    expect(intents.entries).toHaveLength(0)
  })
})

describe('409 (SD9)', () => {
  it('queues a conflict holding the 409 version and price, and promotes on arrival (AC12, PD9)', async () => {
    intents.create(Q, 1)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    expect(promotes).toBe(1)
    const head = intents.headConflict
    expect(head).toMatchObject({ drinkId: 1, quote: { version: 9, prices: { 1: 270 } } })
    expect(Object.isFrozen(head?.quote)).toBe(true)
    expect(intents.entries[0].state).toBe('conflict')
  })

  it('confirm() posts a new key with exactly the 409 version and price (AC13)', async () => {
    intents.create(Q, 1)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    intents.confirm()
    expect(calls).toHaveLength(2)
    expect(calls[1].key).not.toBe(calls[0].key)
    expect(calls[1].body).toEqual({
      quote_version: 9,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 270 }],
    })
    expect(intents.headConflict).toBeNull()
    expect(intents.entries).toHaveLength(1)
    expect(intents.entries[0].state).toBe('sending')
  })

  it('a second 409 on the confirmation opens a new conflict with the newer price', async () => {
    intents.create(Q, 1)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    intents.confirm()
    calls[1].resolve(priceChanged(10, 1, 280))
    await settle()
    expect(intents.headConflict?.quote).toMatchObject({ version: 10, prices: { 1: 280 } })
  })

  it('cancel() posts nothing and shows cancelled for 3 s (AC13, PD7)', async () => {
    intents.create(Q, 1)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    intents.cancel()
    expect(calls).toHaveLength(1)
    expect(intents.headConflict).toBeNull()
    expect(intents.entries[0].state).toBe('cancelled')
    await vi.advanceTimersByTimeAsync(LINGER_MS)
    expect(intents.entries).toHaveLength(0)
  })

  it('two 409s queue in tap order even when they arrive in reverse (AC14)', async () => {
    intents.create(Q, 1)
    intents.create(Q, 2)
    calls[1].resolve(priceChanged(9, 2, 310))
    await settle()
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    expect(intents.headConflict?.drinkId).toBe(1)
    intents.cancel()
    expect(intents.headConflict?.drinkId).toBe(2)
    intents.confirm()
    expect(calls[2].body.lines[0]).toEqual({ drink_id: 2, qty: 1, unit_price_cents: 310 })
    expect(intents.headConflict).toBeNull()
  })

  it('a 409 without a price for the tapped drink fails, never guessing a price', async () => {
    intents.create(Q, 1)
    calls[0].resolve(priceChanged(9, 2, 310))
    await settle()
    expect(intents.headConflict).toBeNull()
    expect(intents.entries[0].state).toBe('failed')
  })
})

describe('other answers', () => {
  it('a 422 is failed with exactly one post, and lingers 3 s (AC15, PD7)', async () => {
    intents.create(Q, 1)
    calls[0].reject(new HttpError(422, 'invalid_order', 'nope'))
    await settle()
    expect(intents.entries[0].state).toBe('failed')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(1)
    expect(intents.entries).toHaveLength(0)
  })

  it('a 401 leaves the entry in flight and never retries (SD8, SD12)', async () => {
    intents.create(Q, 1)
    calls[0].reject(new HttpError(401, 'unauthenticated', ''))
    await settle()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(intents.entries[0].state).toBe('sending')
    expect(calls).toHaveLength(1)
  })

  it('an answer after dispose() changes nothing', async () => {
    intents.create(Q, 1)
    const before = intents.entries
    intents.dispose()
    calls[0].resolve(accepted(calls[0].body))
    await settle()
    expect(intents.entries).toBe(before)
    expect(promotes).toBe(0)
  })
})

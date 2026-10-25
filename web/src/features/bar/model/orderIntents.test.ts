// The order-intent machine on fake timers with a scripted transport
// (Phase 5 T7): SD5-SD10, PD7, PD9, PD11. B-06 T12: a basket of lines and a wallet
// (SD4, SD15, PD12).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '../../../lib/http'
import { quoteFromPriceChanged, type Quote } from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { add, EMPTY, type Basket } from './basket'
import { createOrderIntents, LINGER_MS, RETRY_DELAYS_MS, type OrderIntents } from './orderIntents'

const one = (drinkId: number): Basket => add(EMPTY, drinkId)

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
  const lines = body.lines.map((l, i) => {
    const unit = i === 0 ? unitPriceCents : l.unit_price_cents
    return {
      drink_id: l.drink_id,
      qty: l.qty,
      unit_price_cents: unit,
      line_total_cents: l.qty * unit,
    }
  })
  return {
    kind: 'accepted',
    receipt: {
      order_id: 1,
      version: body.quote_version + 1,
      wall_ts_ms: 0,
      quote_version: body.quote_version,
      lines,
      total_cents: lines.reduce((sum, l) => sum + l.line_total_cents, 0),
      wallet: null,
    },
  }
}

function priceChanged(
  version: number,
  drinkId: number,
  cents: number,
  more: Record<number, number> = {},
): OrderOutcome {
  const others = Object.entries(more).map(([d, c]) => ({ drink_id: Number(d), price_cents: c }))
  return {
    kind: 'price_changed',
    body: { version, prices: [{ drink_id: drinkId, price_cents: cents }, ...others] },
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
    newKey: () => `key-${String(++keys).padStart(4, '0')}`,
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
    intents.create(Q, one(1), null)
    expect(calls).toHaveLength(1)
    expect(calls[0].body).toEqual({
      quote_version: 7,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }],
    })
    expect(Object.isFrozen(calls[0].body)).toBe(true)
    expect(Object.isFrozen(calls[0].body.lines[0])).toBe(true)
    expect(intents.entries[0]).toMatchObject({ lines: one(1), wallet: null, state: 'sending' })
  })

  it('posts every line of a basket at the quote version and prices, in basket order', () => {
    const basket = add(add(add(EMPTY, 2), 1), 2)
    intents.create(Q, basket, null)
    expect(calls[0].body).toEqual({
      quote_version: 7,
      lines: [
        { drink_id: 2, qty: 2, unit_price_cents: 300 },
        { drink_id: 1, qty: 1, unit_price_cents: 250 },
      ],
    })
    expect('wallet' in calls[0].body).toBe(false)
  })

  it('carries the wallet exactly as scanned (B-06 SD13)', () => {
    intents.create(Q, one(1), { short_code: ' k7q4 m2xd ' })
    expect(calls[0].body.wallet).toEqual({ short_code: ' k7q4 m2xd ' })
  })

  it('an empty basket creates nothing', () => {
    expect(intents.create(Q, EMPTY, null)).toBeNull()
    expect(calls).toHaveLength(0)
  })

  it('two creates within 100 ms on one drink post twice with distinct keys (AC9)', () => {
    intents.create(Q, one(1), null)
    vi.advanceTimersByTime(50)
    intents.create(Q, one(1), null)
    expect(calls.map((c) => c.key)).toEqual(['key-0001', 'key-0002'])
  })

  it('a drink missing from the quote creates nothing', () => {
    expect(intents.create(Q, add(one(1), 99), null)).toBeNull()
    expect(calls).toHaveLength(0)
  })
})

describe('success', () => {
  it('a 2xx is accepted with the receipt price, promotes, and lingers 3 s (AC3, PD7)', async () => {
    intents.create(Q, one(1), null)
    calls[0].resolve(accepted(calls[0].body, 260))
    await settle()
    expect(intents.entries[0].state).toBe('accepted')
    expect(intents.entries[0].receipt?.lines[0].unit_price_cents).toBe(260)
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
    intents.create(Q, one(1), null)
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

  it('a 500 or an unreadable 2xx may have been booked: retried with the same key, never failed (SD8)', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(new HttpError(500, 'internal_error', 'boom'))
    await settle()
    expect(intents.entries[0].state).toBe('sending')
    await vi.advanceTimersByTimeAsync(1000)
    expect(calls).toHaveLength(2)
    calls[1].reject(new HttpError(201, 'invalid_response', 'the response body is not valid'))
    await settle()
    expect(intents.entries[0].state).toBe('sending')
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls).toHaveLength(3)
    expect(new Set(calls.map((c) => c.key))).toEqual(new Set(['key-0001']))
  })

  it('a 503 then a 200 replay is one accepted entry (AC26)', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(unavailable())
    await settle()
    await vi.advanceTimersByTimeAsync(1000)
    calls[1].resolve(accepted(calls[1].body))
    await settle()
    expect(intents.entries).toHaveLength(1)
    expect(intents.entries[0].state).toBe('accepted')
    expect(intents.entries[0].receipt?.total_cents).toBe(250)
    expect(calls).toHaveLength(2)
  })

  async function toUnknown(): Promise<number> {
    const id = intents.create(Q, one(1), null)!
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
    intents.create(Q, one(1), null)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    expect(promotes).toBe(1)
    const head = intents.headConflict
    expect(head).toMatchObject({ lines: one(1), quote: { version: 9, prices: { 1: 270 } } })
    expect(head?.body.lines[0].unit_price_cents).toBe(250)
    expect(Object.isFrozen(head?.quote)).toBe(true)
    expect(intents.entries[0].state).toBe('conflict')
  })

  it('confirm() posts a new key with exactly the 409 version and price (AC13)', async () => {
    intents.create(Q, one(1), null)
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
    intents.create(Q, one(1), null)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    intents.confirm()
    calls[1].resolve(priceChanged(10, 1, 280))
    await settle()
    expect(intents.headConflict?.quote).toMatchObject({ version: 10, prices: { 1: 280 } })
  })

  it('cancel() posts nothing and shows cancelled for 3 s (AC13, PD7)', async () => {
    intents.create(Q, one(1), null)
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
    intents.create(Q, one(1), null)
    intents.create(Q, one(2), null)
    calls[1].resolve(priceChanged(9, 2, 310))
    await settle()
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    expect(intents.headConflict?.lines).toEqual(one(1))
    intents.cancel()
    expect(intents.headConflict?.lines).toEqual(one(2))
    intents.confirm()
    expect(calls[2].body.lines[0]).toEqual({ drink_id: 2, qty: 1, unit_price_cents: 310 })
    expect(intents.headConflict).toBeNull()
  })

  it('confirming a basket keeps its lines and wallet, priced from the 409, with a new key (AC11)', async () => {
    const basket = add(add(EMPTY, 1), 2)
    intents.create(Q, basket, { qr_token: 'tok-1' })
    calls[0].resolve(priceChanged(9, 1, 270, { 2: 290 }))
    await settle()
    intents.confirm()
    expect(calls[1].key).not.toBe(calls[0].key)
    expect(calls[1].body).toEqual({
      quote_version: 9,
      lines: [
        { drink_id: 1, qty: 1, unit_price_cents: 270 },
        { drink_id: 2, qty: 1, unit_price_cents: 290 },
      ],
      wallet: { qr_token: 'tok-1' },
    })
  })

  it('a 409 that does not price every line of the basket fails', async () => {
    intents.create(Q, add(one(1), 2), null)
    calls[0].resolve(priceChanged(9, 1, 270))
    await settle()
    expect(intents.headConflict).toBeNull()
    expect(intents.entries[0].state).toBe('failed')
  })

  it('a 409 without a price for the tapped drink fails, never guessing a price', async () => {
    intents.create(Q, one(1), null)
    calls[0].resolve(priceChanged(9, 2, 310))
    await settle()
    expect(intents.headConflict).toBeNull()
    expect(intents.entries[0].state).toBe('failed')
  })
})

describe('other answers', () => {
  it('a 422 is failed with exactly one post, and lingers 3 s (AC15, PD7)', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(new HttpError(422, 'invalid_order', 'nope'))
    await settle()
    expect(intents.entries[0].state).toBe('failed')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(1)
    expect(intents.entries).toHaveLength(0)
  })

  it('a 422 drink_unavailable is unavailable, never retried, and lingers 3 s (Phase 6 SD13)', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(new HttpError(422, 'drink_unavailable', 'removed'))
    await settle()
    expect(intents.entries[0].state).toBe('unavailable')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls).toHaveLength(1)
    expect(intents.entries).toHaveLength(0)
  })

  it.each([
    [409, 'wallet_required', {}],
    [404, 'wallet_not_found', {}],
    [409, 'insufficient_balance', { balance_cents: 750, credit_limit_cents: 0 }],
  ])(
    'a %i %s is refused with its details, never retried, and lingers (B-06 SD15)',
    async (status, code, details) => {
      intents.create(Q, one(1), null)
      calls[0].reject(new HttpError(status, code, 'no', details))
      await settle()
      expect(intents.entries[0]).toMatchObject({ state: 'refused', refusal: { code, details } })
      await vi.advanceTimersByTimeAsync(60_000)
      expect(calls).toHaveLength(1)
      expect(intents.entries).toHaveLength(0)
    },
  )

  it('a 401 leaves the entry in flight and never retries (SD8, SD12)', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(new HttpError(401, 'unauthenticated', ''))
    await settle()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(intents.entries[0].state).toBe('sending')
    expect(calls).toHaveLength(1)
  })

  it('an answer after dispose() changes nothing', async () => {
    intents.create(Q, one(1), null)
    const before = intents.entries
    intents.dispose()
    calls[0].resolve(accepted(calls[0].body))
    await settle()
    expect(intents.entries).toBe(before)
    expect(promotes).toBe(0)
  })
})

describe('a close racing an order (Phase 7 T17, R15)', () => {
  it('409 no_live_run is terminal: failed, never retried, then gone', async () => {
    intents.create(Q, one(1), null)
    calls[0].reject(new HttpError(409, 'no_live_run', 'there is no live run'))
    await settle()
    expect(intents.entries[0].state).toBe('failed')

    await vi.advanceTimersByTimeAsync(RETRY_DELAYS_MS.reduce((a, b) => a + b, 0) + LINGER_MS)
    expect(calls).toHaveLength(1)
    expect(intents.entries).toHaveLength(0)
  })
})

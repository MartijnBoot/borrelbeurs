// The Quote builders (Phase 5 T4: AC2, SD2, PD2, PD4): each takes one message
// and returns frozen data carrying exactly that message's version and prices.
import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/ws-messages.json'
import {
  type Quote,
  quoteFromOrder,
  quoteFromPriceChanged,
  quoteFromSnapshot,
  quoteFromTick,
} from './quote'
import { ServerMessage } from './schemas'

type Of<K extends ServerMessage['type']> = Extract<ServerMessage, { type: K }>

function frame<K extends keyof typeof fixture>(name: K): ServerMessage {
  return ServerMessage.parse(structuredClone(fixture[name]))
}

const snapshot = frame('snapshot') as Of<'snapshot'>
const tick = frame('tick') as Of<'tick'>
const order = frame('order') as Of<'order'>

function expectDeeplyFrozen(quote: Quote | null): void {
  expect(quote).not.toBeNull()
  expect(Object.isFrozen(quote)).toBe(true)
  expect(Object.isFrozen(quote?.prices)).toBe(true)
}

describe('quoteFromSnapshot', () => {
  it("carries the snapshot's data.version and every drink's price_cents", () => {
    const quote = quoteFromSnapshot(snapshot.data, 7)
    expect(quote.version).toBe(snapshot.data.version)
    expect(quote.prices).toEqual({ 1: 270, 2: 260, 3: 250 })
    expect(quote.receivedAt).toBe(7)
    expectDeeplyFrozen(quote)
  })

  it('does not alias the message: changing it afterwards changes nothing', () => {
    const data = structuredClone(snapshot.data)
    const quote = quoteFromSnapshot(data, 0)
    data.prices['1'].price_cents = 999
    data.version = 999
    expect(quote.prices[1]).toBe(270)
    expect(quote.version).toBe(snapshot.data.version)
  })
})

describe('quoteFromTick', () => {
  it("carries the envelope's version and each drink's price_cents, not chart_price_cents", () => {
    const quote = quoteFromTick(tick, 3)
    expect(quote?.version).toBe(tick.version)
    expect(quote?.prices).toEqual({ 1: 260, 2: 260, 3: 260 })
    expect(quote?.receivedAt).toBe(3)
    expectDeeplyFrozen(quote)
  })

  it('is null for an envelope without a version (PD4)', () => {
    expect(quoteFromTick({ ...tick, version: null }, 3)).toBeNull()
  })
})

describe('quoteFromOrder', () => {
  it("carries the envelope's version and the order's prices", () => {
    const quote = quoteFromOrder(order, 4)
    expect(quote?.version).toBe(order.version)
    expect(quote?.prices).toEqual({ 1: 270, 2: 260, 3: 250 })
    expectDeeplyFrozen(quote)
  })

  it('is null for an envelope without a version (PD4)', () => {
    expect(quoteFromOrder({ ...order, version: null }, 4)).toBeNull()
  })
})

describe('quoteFromPriceChanged', () => {
  it("carries the 409 body's version and line prices", () => {
    const quote = quoteFromPriceChanged(
      {
        version: 9,
        prices: [
          { drink_id: 1, price_cents: 280 },
          { drink_id: 3, price_cents: 240 },
        ],
      },
      5,
    )
    expect(quote.version).toBe(9)
    expect(quote.prices).toEqual({ 1: 280, 3: 240 })
    expect(quote.receivedAt).toBe(5)
    expectDeeplyFrozen(quote)
  })
})

describe('frozen', () => {
  it('rejects writes in strict mode', () => {
    const quote = quoteFromSnapshot(snapshot.data, 0)
    expect(() => {
      ;(quote as { version: number }).version = 1
    }).toThrow(TypeError)
    expect(() => {
      ;(quote.prices as Record<number, number>)[1] = 1
    }).toThrow(TypeError)
  })
})

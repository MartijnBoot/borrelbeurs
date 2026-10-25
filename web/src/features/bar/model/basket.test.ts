// The basket (B-06 T12: SD4, AC17, PD12): pure lines of {drink, qty}, priced only from a
// displayed Quote.
import { describe, expect, it } from 'vitest'
import { quoteFromPriceChanged, type Quote } from '../../exchange'
import {
  add,
  EMPTY,
  lineCents,
  linesText,
  MAX_QTY,
  remove,
  shortfallCents,
  totalCents,
  type Basket,
} from './basket'

function quote(version: number, prices: Record<number, number>): Quote {
  const lines = Object.entries(prices).map(([id, cents]) => ({
    drink_id: Number(id),
    price_cents: cents,
  }))
  return quoteFromPriceChanged({ version, prices: lines }, 0)
}

const Q = quote(7, { 1: 250, 2: 300, 3: 0 })

function times(n: number, drinkId: number, basket: Basket = EMPTY): Basket {
  let out = basket
  for (let i = 0; i < n; i++) out = add(out, drinkId)
  return out
}

describe('the basket (AC17)', () => {
  it('a tap adds one; a second drink is a second line, in tap order', () => {
    const basket = add(add(add(EMPTY, 1), 2), 1)
    expect(basket).toEqual([
      { drinkId: 1, qty: 2 },
      { drinkId: 2, qty: 1 },
    ])
  })

  it('a line holds at most 99', () => {
    expect(MAX_QTY).toBe(99)
    expect(times(100, 1)).toEqual([{ drinkId: 1, qty: 99 }])
  })

  it('"−" takes one off, and at 0 removes the line', () => {
    const basket = times(2, 1, add(EMPTY, 2))
    expect(remove(basket, 1)).toEqual([
      { drinkId: 2, qty: 1 },
      { drinkId: 1, qty: 1 },
    ])
    expect(remove(remove(basket, 1), 1)).toEqual([{ drinkId: 2, qty: 1 }])
    expect(remove(basket, 3)).toBe(basket)
  })

  it('is never changed in place', () => {
    const basket = add(EMPTY, 1)
    expect(Object.isFrozen(basket)).toBe(true)
    expect(Object.isFrozen(basket[0])).toBe(true)
    add(basket, 1)
    expect(basket).toEqual([{ drinkId: 1, qty: 1 }])
  })
})

describe('the price on screen (AC17, SD18)', () => {
  it('a line and the total come from the quote', () => {
    const basket = times(2, 1, add(EMPTY, 2))
    expect(lineCents(basket[0], Q)).toBe(300)
    expect(lineCents(basket[1], Q)).toBe(500)
    expect(totalCents(basket, Q)).toBe(800)
    expect(totalCents(EMPTY, Q)).toBe(0)
  })

  it('a free drink costs nothing', () => {
    expect(totalCents(times(3, 3), Q)).toBe(0)
  })

  it('is null when a price is missing, or there is no quote', () => {
    expect(totalCents(add(EMPTY, 9), Q)).toBeNull()
    expect(lineCents({ drinkId: 9, qty: 1 }, Q)).toBeNull()
    expect(totalCents(add(EMPTY, 1), null)).toBeNull()
  })

  it('the shortfall is what the total exceeds balance + limit by, never below 0', () => {
    expect(shortfallCents(1250, 750, 0)).toBe(500)
    expect(shortfallCents(1000, 750, 250)).toBe(0)
    expect(shortfallCents(1001, 750, 250)).toBe(1)
    expect(shortfallCents(100, -300, 250)).toBe(150)
  })
})

describe('the lines as words', () => {
  it('"1× Wijn, 2× Bier", in the basket order', () => {
    const names: Record<number, string> = { 1: 'Bier', 2: 'Wijn' }
    expect(linesText(times(2, 1, add(EMPTY, 2)), (id) => names[id])).toBe('1× Wijn, 2× Bier')
  })
})

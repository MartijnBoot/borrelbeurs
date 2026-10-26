/**
 * The bar's basket (B-06 SD4, AC17, PD12): an ordered list of `{drinkId, qty}`, one
 * line per drink in the order first tapped, each 1-99 as the server allows. Pure and
 * frozen; the controller holds the current one.
 *
 * Every price here is read from the `Quote` the caller passes -- the displayed one
 * (Phase 5 SD1, SD2) -- so the total on screen is the total the order carries. This
 * is the price on screen, not revenue: revenue still comes only from the server's
 * receipts and `earnings` (Phase 5 AC17). It is the one file exempt from the lint
 * rule against `qty *` (PD13).
 */
import type { DrinkId, Quote } from '../../exchange'

/** The server's bound on a line's `qty` (`app/api/orders.py`). */
export const MAX_QTY = 99

export interface BasketLine {
  readonly drinkId: DrinkId
  readonly qty: number
}

export type Basket = readonly BasketLine[]

export const EMPTY: Basket = Object.freeze([])

function line(drinkId: DrinkId, qty: number): BasketLine {
  return Object.freeze({ drinkId, qty })
}

/** One more of `drinkId`: a new last line, or its line + 1, up to `MAX_QTY`. */
export function add(basket: Basket, drinkId: DrinkId): Basket {
  const found = basket.find((l) => l.drinkId === drinkId)
  if (found === undefined) return Object.freeze([...basket, line(drinkId, 1)])
  if (found.qty >= MAX_QTY) return basket
  return Object.freeze(basket.map((l) => (l === found ? line(drinkId, l.qty + 1) : l)))
}

/** One fewer of `drinkId`; a line at 0 goes. */
export function remove(basket: Basket, drinkId: DrinkId): Basket {
  const found = basket.find((l) => l.drinkId === drinkId)
  if (found === undefined) return basket
  if (found.qty <= 1) return Object.freeze(basket.filter((l) => l !== found))
  return Object.freeze(basket.map((l) => (l === found ? line(drinkId, l.qty - 1) : l)))
}

/** The line's price in `quote`, or `null` when the quote has none for the drink. */
export function lineCents(basketLine: BasketLine, quote: Quote | null): number | null {
  const price = quote?.prices[basketLine.drinkId]
  return price === undefined ? null : basketLine.qty * price
}

/** The basket's total in `quote`, or `null` when any price is missing. */
export function totalCents(basket: Basket, quote: Quote | null): number | null {
  if (quote === null) return null
  let total = 0
  for (const basketLine of basket) {
    const cents = lineCents(basketLine, quote)
    if (cents === null) return null
    total += cents
  }
  return total
}

/** What `total` exceeds balance + limit by, or 0 (SD18). */
export function shortfallCents(total: number, balanceCents: number, limitCents: number): number {
  return Math.max(0, total - (balanceCents + limitCents))
}

/** An order body's total: what the bar asked the wallet to pay (B-06 SD18). */
export function bodyCents(
  lines: readonly { readonly qty: number; readonly unit_price_cents: number }[],
): number {
  return lines.reduce((sum, l) => sum + l.qty * l.unit_price_cents, 0)
}

/** "2× Bier, 1× Wijn", in the basket's order. */
export function linesText(basket: Basket, nameOf: (drinkId: DrinkId) => string): string {
  return basket.map((l) => `${l.qty}× ${nameOf(l.drinkId)}`).join(', ')
}

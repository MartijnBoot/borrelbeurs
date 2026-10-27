/**
 * Price bounds on the Prijsstap grid (B-07 SD1, SD3, SD6, SD10; plan PD8). It
 * mirrors `app/runtime/price_grid.py`: "on the grid" is decided in whole cents,
 * a bound off it is refused with its two grid neighbours, and a new step moves
 * every active drink's off-grid bound inward (Minimum up, Maximum down). The
 * server stays the authority; the page checks first and warns (SD10).
 * `grid.test.ts` and `tests/unit/test_price_grid.py` pin the same texts.
 */
import { centsText } from '../../lib/format'

export type BoundField = 'p_min_cents' | 'p_max_cents'

export interface BoundMove {
  name: string
  field: BoundField
  from: number
  to: number
}

interface PricedDrink {
  name: string
  slot: number
  active: boolean
  p_min_cents: number
  p_max_cents: number
}

/** The Prijsstap in whole cents: 0.1 is 10. */
export function stepCents(step: number): number {
  return Math.round(step * 100)
}

export function onGrid(cents: number, step: number): boolean {
  return cents % step === 0
}

/** The grid points either side of an off-grid `cents`. */
export function neighbours(cents: number, step: number): [number, number] {
  const lower = Math.floor(cents / step) * step
  return [lower, lower + step]
}

/** SD1's refusal: "Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30." */
export function gridMessage(cents: number, step: number): string {
  const [lower, upper] = neighbours(cents, step)
  return `Moet een veelvoud van de Prijsstap (${centsText(step)}) zijn: ${centsText(lower)} of ${centsText(upper)}.`
}

/** SD6's warning under a stored off-grid bound: "Niet op de Prijsstap: kies 1,20 of 1,30." */
export function offGridHint(cents: number, step: number): string {
  const [lower, upper] = neighbours(cents, step)
  return `Niet op de Prijsstap: kies ${centsText(lower)} of ${centsText(upper)}.`
}

/** SD3's moves for a new step, over the active drinks in slot order, Minimum first. */
export function boundMoves(drinks: readonly PricedDrink[], step: number): BoundMove[] {
  const moves: BoundMove[] = []
  for (const drink of [...drinks].sort((a, b) => a.slot - b.slot)) {
    if (!drink.active) continue
    const low = Math.ceil(drink.p_min_cents / step) * step
    const high = Math.floor(drink.p_max_cents / step) * step
    if (low !== drink.p_min_cents) {
      moves.push({ name: drink.name, field: 'p_min_cents', from: drink.p_min_cents, to: low })
    }
    if (high !== drink.p_max_cents) {
      moves.push({ name: drink.name, field: 'p_max_cents', from: drink.p_max_cents, to: high })
    }
  }
  return moves
}

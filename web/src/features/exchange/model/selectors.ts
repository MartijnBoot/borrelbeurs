import type { DrinkId, ExchangeState } from './applyMessage'
import type { MarketEventInfo } from './schemas'

export type PulseDirection = 'rising' | 'falling'

/** SD23: the last change of a drink's displayed price; `null` if none, or after a snapshot. */
export function pulseDirection(state: ExchangeState, drinkId: DrinkId): PulseDirection | null {
  const current = state.prices[drinkId]?.price_cents
  const previous = state.prevPriceCents[drinkId]
  if (current === undefined || previous === undefined || current === previous) return null
  return current > previous ? 'rising' : 'falling'
}

export const selectDrinks = (state: ExchangeState) => state.drinks
const activeOf = new WeakMap<ExchangeState['drinks'], ExchangeState['drinks']>()

/**
 * The drinks not removed from the live run (Phase 6 SD18), in slot order.
 * Memoised on `drinks`, so a `useExchange` selector gets the same array back
 * until a snapshot or `config` replaces it.
 */
export function selectActiveDrinks(state: ExchangeState): ExchangeState['drinks'] {
  let active = activeOf.get(state.drinks)
  if (active === undefined) {
    active = state.drinks.filter((d) => d.active)
    activeOf.set(state.drinks, active)
  }
  return active
}
export const selectPrice = (state: ExchangeState, drinkId: DrinkId) => state.prices[drinkId]
export const selectBars = (state: ExchangeState, drinkId: DrinkId) => state.bars[drinkId]
export const selectNews = (state: ExchangeState) => state.news
export const selectMarketEvents = (state: ExchangeState) => state.marketEvents

/**
 * Whole seconds left of a market event (Phase 6 SD22) at `serverNowMs`, the
 * server's clock (`Date.now()` plus the skew offset): rounded up, never below 0.
 */
export function eventSecondsLeft(event: MarketEventInfo, serverNowMs: number): number {
  return Math.max(0, Math.ceil((event.t_end_ms - serverNowMs) / 1000))
}
export const selectTheme = (state: ExchangeState) => state.theme
export const selectStatus = (state: ExchangeState) => state.status
export const selectEmpty = (state: ExchangeState) => state.empty
export const selectQuote = (state: ExchangeState) => state.quote
export const selectEarnings = (state: ExchangeState) => state.earnings
/** The run a `run_closed` just ended, until the next snapshot (Phase 7 PD5). */
export const selectClosedRun = (state: ExchangeState) => state.closedRun

/** The panel's totals (SD15): sums of the server's per-drink numbers, nothing derived. */
export function selectTotals(state: ExchangeState): { revenueCents: number; qty: number } {
  let revenueCents = 0
  let qty = 0
  for (const line of Object.values(state.earnings)) {
    revenueCents += line.revenue_cents
    qty += line.qty
  }
  return { revenueCents, qty }
}

import type { DrinkId, ExchangeState } from './applyMessage'

export type PulseDirection = 'rising' | 'falling'

/** SD23: the last change of a drink's displayed price; `null` if none, or after a snapshot. */
export function pulseDirection(state: ExchangeState, drinkId: DrinkId): PulseDirection | null {
  const current = state.prices[drinkId]?.price_cents
  const previous = state.prevPriceCents[drinkId]
  if (current === undefined || previous === undefined || current === previous) return null
  return current > previous ? 'rising' : 'falling'
}

export const selectDrinks = (state: ExchangeState) => state.drinks
export const selectPrice = (state: ExchangeState, drinkId: DrinkId) => state.prices[drinkId]
export const selectBars = (state: ExchangeState, drinkId: DrinkId) => state.bars[drinkId]
export const selectNews = (state: ExchangeState) => state.news
export const selectMarketEvents = (state: ExchangeState) => state.marketEvents
export const selectTheme = (state: ExchangeState) => state.theme
export const selectStatus = (state: ExchangeState) => state.status
export const selectEmpty = (state: ExchangeState) => state.empty
export const selectQuote = (state: ExchangeState) => state.quote

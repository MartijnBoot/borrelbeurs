// The exchange feature's public surface: the one store, its selectors, and
// the SMA. Live state is written only by frames from the WebSocket client.
// The reducer itself is exported for the bar's property test (Phase 5 T8),
// which drives a store of its own through it.
export type { DrinkId, ExchangeState, Status } from './model/applyMessage'
export { applyMessage, applyPolledState, initialState } from './model/applyMessage'
export type {
  Bar,
  DrinkEarnings,
  DrinkPrice,
  MarketEventInfo,
  NewsItem,
  ServerMessage,
  SnapshotData,
  ThemeData,
} from './model/schemas'
export { exchangeStore, useExchange } from './model/store'
export { type PriceChanged, type Quote, quoteFromPriceChanged } from './model/quote'
export * from './model/selectors'
export { SMA_WINDOW, smaSeries, type SmaPoint } from './model/sma'
export {
  createExchangeClient,
  type ExchangeClient,
  type ExchangeClientDeps,
  type SocketLike,
} from './model/client'

/**
 * The one store (frontend-architecture.md, "State"), created once and
 * subscribable outside React: a chart's `series.update` hangs off
 * `exchangeStore.subscribe`, so a tick causes no React render.
 *
 * Live state is written only by `dispatch`, with frames from the WebSocket
 * client; `setStatus` and `setSkewOffset` are the client's own bookkeeping.
 */
import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'
import { applyMessage, initialState, type ExchangeState, type Status } from './applyMessage'
import type { ServerMessage } from './schemas'

export const exchangeStore = createStore<ExchangeState>(() => initialState)

export function dispatch(message: ServerMessage): void {
  exchangeStore.setState((state) => applyMessage(state, message), true)
}

export function setStatus(status: Status): void {
  exchangeStore.setState({ status })
}

export function setSkewOffset(skewOffsetMs: number): void {
  exchangeStore.setState({ skewOffsetMs })
}

export function useExchange<T>(selector: (state: ExchangeState) => T): T {
  return useStore(exchangeStore, selector)
}

// The bar controller's example cases (Phase 5 T8, PD3, PD8): the wiring the
// property test then hammers. Real store and reducer, fake timers, a scripted
// transport.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createStore, type StoreApi } from 'zustand/vanilla'
import {
  applyMessage,
  initialState,
  type ExchangeState,
  type ServerMessage,
  type SnapshotData,
} from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { createBarController, type BarController } from './barController'
import { HOLD_MS, STALE_MS } from './constants'

const THEME = { preset: 'blauw' as const, revision: 0, tokens: {}, font_family: 'sans-serif' }
const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
}

function envelope<T extends ServerMessage['type']>(
  type: T,
  seq: number,
  version: number | null,
  data: Extract<ServerMessage, { type: T }>['data'],
): ServerMessage {
  return { v: 1, type, seq, ts_ms: 0, run_id: 1, version, data } as ServerMessage
}

function snapshotData(version: number, cents: number): SnapshotData {
  return {
    version,
    run: RUN,
    drinks: [{ drink_id: 1, name: 'Bier', active: true }],
    params: {},
    prices: { 1: { price_cents: cents, chart_price_cents: cents } },
    bars: {},
    news: [],
    earnings: {},
    market_events: [],
  }
}

function tick(seq: number, version: number, cents: number): ServerMessage {
  return envelope('tick', seq, version, {
    candle_t_ms: 0,
    drinks: {
      1: { price_cents: cents, chart_price_cents: cents, candle: [cents, cents, cents, cents] },
    },
  })
}

let store: StoreApi<ExchangeState>
let controller: BarController
let posts: { key: string; body: OrderBody; resolve(o: OrderOutcome): void }[]
let seq: number

function dispatch(message: ServerMessage) {
  store.setState((state) => applyMessage(state, message, Date.now()), true)
}

beforeEach(() => {
  vi.useFakeTimers()
  store = createStore<ExchangeState>(() => initialState)
  posts = []
  seq = 1
  controller = createBarController({
    store,
    now: () => Date.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    post: ({ key, body }) =>
      new Promise<OrderOutcome>((resolve) => posts.push({ key, body, resolve })),
    uuid: () => `key-${String(posts.length).padStart(4, '0')}-${Math.random()}`,
  })
  dispatch(
    envelope('hello', seq, null, {
      boot_id: 'BOOT',
      run_id: 1,
      tick_interval_ms: 1000,
      protocol: 1,
      role: 'bar',
      theme: THEME,
    }),
  )
  dispatch(envelope('snapshot', seq, 5, snapshotData(5, 250)))
})

afterEach(() => {
  controller.dispose()
  vi.useRealTimers()
})

const price = () => controller.view.displayed?.prices[1]

describe('the bar controller', () => {
  it('offers each new store quote to the hold buffer', () => {
    expect(controller.view.displayed).toBe(store.getState().quote)
    dispatch(tick(++seq, 6, 260))
    expect(price()).toBe(260)
  })

  it('a tap posts the displayed quote, not the latest, inside a hold (PD8)', () => {
    controller.press()
    dispatch(tick(++seq, 6, 260))
    controller.release()
    controller.tap(1)
    expect(posts[0].body).toEqual({
      quote_version: 5,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }],
    })
    vi.advanceTimersByTime(HOLD_MS)
    expect(price()).toBe(260)
  })

  it('a snapshot force-promotes inside a hold (PD3)', () => {
    controller.press()
    dispatch(tick(++seq, 6, 260))
    dispatch(envelope('snapshot', seq, 7, snapshotData(7, 270)))
    expect(controller.view.displayed?.version).toBe(7)
  })

  it('a 409 force-promotes inside a hold, and an accepted order does too (SD3)', async () => {
    controller.press()
    controller.tap(1)
    dispatch(tick(++seq, 6, 260))
    expect(price()).toBe(250)
    posts[0].resolve({
      kind: 'price_changed',
      body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(price()).toBe(260)
    expect(controller.view.headConflict?.quote.prices[1]).toBe(260)

    controller.confirm()
    dispatch(tick(++seq, 7, 270))
    expect(price()).toBe(260) // still held
    const body = posts[1].body
    posts[1].resolve({
      kind: 'accepted',
      receipt: {
        order_id: 1,
        version: 8,
        wall_ts_ms: 0,
        quote_version: body.quote_version,
        lines: [{ drink_id: 1, qty: 1, unit_price_cents: 260, line_total_cents: 260 }],
        total_cents: 260,
      },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(price()).toBe(270)
  })

  it('refresh() promotes (Ververs)', () => {
    controller.press()
    dispatch(tick(++seq, 6, 260))
    controller.refresh()
    expect(price()).toBe(260)
  })

  it('refuses a tap while a conflict is open (AC14)', async () => {
    controller.tap(1)
    posts[0].resolve({
      kind: 'price_changed',
      body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.tap(1)).toBeNull()
    expect(posts).toHaveLength(1)
  })

  it('refuses a tap when the latest quote is stale (AC8), and accepts one after a fresh tick', () => {
    vi.advanceTimersByTime(STALE_MS + 1)
    expect(controller.tap(1)).toBeNull()
    expect(posts).toHaveLength(0)
    dispatch(tick(++seq, 6, 260))
    expect(controller.tap(1)).not.toBeNull()
    expect(posts).toHaveLength(1)
  })

  it('refuses a tap with no displayed quote', () => {
    dispatch(
      envelope('hello', 1, null, {
        boot_id: 'OTHER',
        run_id: 1,
        tick_interval_ms: 1000,
        protocol: 1,
        role: 'bar',
        theme: THEME,
      }),
    )
    expect(controller.view.displayed).toBeNull()
    expect(controller.tap(1)).toBeNull()
  })

  it('notifies subscribers with a new view, and stops after dispose()', () => {
    const listener = vi.fn()
    const unsubscribe = controller.subscribe(listener)
    const before = controller.view
    dispatch(tick(++seq, 6, 260))
    expect(listener).toHaveBeenCalled()
    expect(controller.view).not.toBe(before)
    unsubscribe()
    controller.dispose()
    listener.mockClear()
    dispatch(tick(++seq, 7, 270))
    expect(listener).not.toHaveBeenCalled()
  })
})

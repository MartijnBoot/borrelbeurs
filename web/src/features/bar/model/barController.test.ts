// The bar controller's example cases (Phase 5 T8, PD3, PD8): the wiring the
// property test then hammers. Real store and reducer, fake timers, a scripted
// transport.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createStore, type StoreApi } from 'zustand/vanilla'
import { HttpError } from '../../../lib/http'
import {
  applyMessage,
  initialState,
  type ExchangeState,
  type ServerMessage,
  type SnapshotData,
} from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { createBarController, type BarController } from './barController'
import { HOLD_MS, STALE_MS, WALLET_IDLE_MS } from './constants'

const THEME = {
  preset: 'blauw' as const,
  revision: 0,
  tokens: {},
  font_family: 'sans-serif',
  images: { bg: null, header: null, logo: null, promo: null },
}
const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
  wallet_required: false,
  credit_limit_cents: 0,
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
let posts: {
  key: string
  body: OrderBody
  resolve(o: OrderOutcome): void
  reject(error: unknown): void
}[]
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
      new Promise<OrderOutcome>((resolve, reject) => posts.push({ key, body, resolve, reject })),
    newKey: () => `key-${String(posts.length).padStart(4, '0')}-${Math.random()}`,
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
/** B-06: a drink into the basket, then "Afrekenen". */
const buy = (drinkId: number) => {
  controller.add(drinkId)
  return controller.checkout()
}

describe('letting go (B-06 T14: SD6, AC19, PD15)', () => {
  const JAN = { query: { qr_token: 'tok-jan' }, name: 'Jan', balance_cents: 1500 }
  const holding = () => [controller.view.wallet?.name ?? null, controller.view.basket.length]

  it('60 s with no tap clears the wallet and the basket; 59 999 ms keeps both', () => {
    expect(WALLET_IDLE_MS).toBe(60_000)
    controller.hold(JAN)
    controller.add(1)
    vi.advanceTimersByTime(59_999)
    expect(holding()).toEqual(['Jan', 1])
    vi.advanceTimersByTime(1)
    expect(holding()).toEqual([null, 0])
  })

  it('a basket alone is let go too', () => {
    controller.add(1)
    vi.advanceTimersByTime(60_000)
    expect(holding()).toEqual([null, 0])
  })

  it('a tap at 30 s restarts the 60 s', () => {
    controller.hold(JAN)
    vi.advanceTimersByTime(30_000)
    controller.touch()
    vi.advanceTimersByTime(59_999)
    expect(holding()).toEqual(['Jan', 0])
    vi.advanceTimersByTime(1)
    expect(holding()).toEqual([null, 0])
  })

  it("never clears while the basket's order is open, and restarts once it settles", async () => {
    controller.hold(JAN)
    buy(1)
    vi.advanceTimersByTime(120_000)
    expect(holding()).toEqual(['Jan', 1])
    posts[0].reject(new HttpError(404, 'other', 'no'))
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.view.basketLocked).toBe(false)
    vi.advanceTimersByTime(59_999)
    expect(holding()).toEqual(['Jan', 1])
    vi.advanceTimersByTime(1)
    expect(holding()).toEqual([null, 0])
  })

  it('"Andere wallet" lets go of the wallet and keeps the basket', () => {
    controller.hold(JAN)
    controller.add(1)
    controller.otherWallet()
    expect(holding()).toEqual([null, 1])
  })

  it('"Annuleren" lets go of both', () => {
    controller.hold(JAN)
    controller.add(1)
    controller.abandon()
    expect(holding()).toEqual([null, 0])
  })

  it('neither works while the order is open (PD12)', () => {
    controller.hold(JAN)
    buy(1)
    controller.otherWallet()
    controller.abandon()
    expect(holding()).toEqual(['Jan', 1])
  })

  it('nothing held arms no timer', () => {
    controller.touch()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("a refund's fresh balance replaces the held one, for the wallet as scanned (AC18)", () => {
    controller.hold(JAN)
    controller.updateBalance(JAN.query, 2340)
    expect(controller.view.wallet).toEqual({ ...JAN, balance_cents: 2340 })
  })

  it('a fresh balance for a wallet no longer held changes nothing', () => {
    controller.updateBalance(JAN.query, 2340)
    expect(controller.view.wallet).toBeNull()
    controller.hold(JAN)
    controller.updateBalance({ qr_token: 'tok-piet' }, 99)
    expect(controller.view.wallet?.balance_cents).toBe(1500)
  })

  it('a fresh balance restarts no idle wait', () => {
    controller.hold(JAN)
    vi.advanceTimersByTime(30_000)
    controller.updateBalance(JAN.query, 2340)
    vi.advanceTimersByTime(30_000)
    expect(holding()).toEqual([null, 0])
  })
})

describe('the bar controller', () => {
  it('offers each new store quote to the hold buffer', () => {
    expect(controller.view.displayed).toBe(store.getState().quote)
    dispatch(tick(++seq, 6, 260))
    expect(price()).toBe(260)
  })

  it('a checkout posts the displayed quote, not the latest, inside a hold (PD8)', () => {
    controller.press()
    dispatch(tick(++seq, 6, 260))
    controller.release()
    buy(1)
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
    buy(1)
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

  it('refuses a checkout while a conflict is open (AC14)', async () => {
    buy(1)
    posts[0].resolve({
      kind: 'price_changed',
      body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(buy(1)).toBeNull()
    expect(posts).toHaveLength(1)
  })

  it('refuses a checkout when the latest quote is stale (AC8), and accepts one after a fresh tick', () => {
    vi.advanceTimersByTime(STALE_MS + 1)
    expect(buy(1)).toBeNull()
    expect(posts).toHaveLength(0)
    dispatch(tick(++seq, 6, 260))
    expect(buy(1)).not.toBeNull()
    expect(posts).toHaveLength(1)
  })

  it('refuses a checkout with no displayed quote', () => {
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
    expect(buy(1)).toBeNull()
  })

  it('a drink tap only adds to the basket: no request (B-06 SD4)', () => {
    controller.add(1)
    controller.add(1)
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 2 }])
    expect(posts).toHaveLength(0)
    controller.remove(1)
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 1 }])
    controller.clear()
    expect(controller.view.basket).toEqual([])
  })

  it('an empty basket does not check out', () => {
    expect(controller.checkout()).toBeNull()
    expect(posts).toHaveLength(0)
  })

  it('locks the basket while its order is open, and clears it once accepted (PD12)', async () => {
    buy(1)
    expect(controller.view.basketLocked).toBe(true)
    controller.add(1)
    controller.clear()
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 1 }])
    expect(controller.checkout()).toBeNull()
    expect(posts).toHaveLength(1)
    posts[0].resolve({
      kind: 'accepted',
      receipt: {
        order_id: 1,
        version: 6,
        wall_ts_ms: 0,
        quote_version: 5,
        lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250, line_total_cents: 250 }],
        total_cents: 250,
        wallet: null,
      },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.view.basket).toEqual([])
    expect(controller.view.basketLocked).toBe(false)
  })

  it('keeps the basket through a 409 and a cancel, unlocked (AC11)', async () => {
    buy(1)
    posts[0].resolve({
      kind: 'price_changed',
      body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.view.basketLocked).toBe(true)
    controller.cancel()
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 1 }])
    expect(controller.view.basketLocked).toBe(false)
  })

  it('clears the basket when an unknown order is dismissed: it may have been booked', async () => {
    buy(1)
    for (const delay of [0, 1000, 2000, 4000]) {
      await vi.advanceTimersByTimeAsync(delay)
      posts[posts.length - 1].reject(new TypeError('Failed to fetch'))
      await vi.advanceTimersByTimeAsync(0)
    }
    expect(controller.view.entries[0].state).toBe('unknown')
    expect(controller.view.basketLocked).toBe(true)
    controller.dismiss(controller.view.entries[0].id)
    expect(controller.view.basket).toEqual([])
    expect(controller.view.basketLocked).toBe(false)
    expect(controller.checkout()).toBeNull()
  })

  it('keeps the basket on a refusal, unlocked (B-06 SD15)', async () => {
    buy(1)
    posts[0].reject(new HttpError(409, 'wallet_required', 'scan one'))
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.view.entries[0].state).toBe('refused')
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 1 }])
    expect(controller.view.basketLocked).toBe(false)
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

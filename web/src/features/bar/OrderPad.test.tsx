// @vitest-environment jsdom
// OrderPad (Phase 5 T10) over a real controller and the real store, on fake
// timers that include performance.now: SD1, SD4, SD5, SD11, PD10.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import {
  applyMessage,
  applyPolledState,
  exchangeStore,
  initialState,
  type ServerMessage,
  type SnapshotData,
} from '../exchange'
import type { OrderBody, OrderOutcome } from './api/orders'
import { createBarController, type BarController } from './model/barController'
import { AGE_SHOW_MS, STALE_MS } from './model/constants'
import { OrderPad } from './OrderPad'

const THEME = { preset: 'blauw' as const, revision: 0, tokens: {}, font_family: 'sans-serif' }
const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
}
const STALE_TEXT = 'Geen actuele prijzen — wacht op verbinding'

function snapshotData(version: number, bier: number, cola: number): SnapshotData {
  return {
    version,
    run: RUN,
    drinks: [
      { drink_id: 1, name: 'Bier', active: true },
      { drink_id: 2, name: 'Cola', active: true },
    ],
    params: {},
    prices: {
      1: { price_cents: bier, chart_price_cents: bier },
      2: { price_cents: cola, chart_price_cents: cola },
    },
    bars: {},
    news: [],
    earnings: {},
    market_events: [],
  }
}

let seq = 1
function message(type: ServerMessage['type'], version: number | null, data: unknown) {
  return { v: 1, type, seq, ts_ms: 0, run_id: 1, version, data } as ServerMessage
}

function dispatch(m: ServerMessage) {
  act(() => exchangeStore.setState((s) => applyMessage(s, m, performance.now()), true))
}

function tick(version: number, bier: number) {
  seq += 1
  const drink = (c: number) => ({ price_cents: c, chart_price_cents: c, candle: [c, c, c, c] })
  dispatch(message('tick', version, { candle_t_ms: 0, drinks: { 1: drink(bier), 2: drink(300) } }))
}

let controller: BarController
let posts: OrderBody[]

function Harness() {
  const view = useSyncExternalStore(controller.subscribe, () => controller.view)
  return <OrderPad view={view} actions={controller} />
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'],
  })
  seq = 1
  exchangeStore.setState(initialState, true)
  posts = []
  controller = createBarController({
    store: exchangeStore,
    now: () => performance.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    post: ({ body }) => {
      posts.push(body)
      return new Promise<OrderOutcome>(() => {})
    },
    uuid: () => crypto.randomUUID(),
  })
  const hello = {
    boot_id: 'B',
    run_id: 1,
    tick_interval_ms: 1000,
    protocol: 1,
    role: 'bar',
    theme: THEME,
  }
  dispatch(message('hello', null, hello))
  dispatch(message('snapshot', 5, snapshotData(5, 250, 300)))
  render(<Harness />)
})

afterEach(() => {
  cleanup()
  controller.dispose()
  vi.useRealTimers()
})

const bier = () => screen.getByRole('button', { name: /^\+1 Bier/ })
const drinkButtons = () => screen.getAllByRole('button', { name: /^\+1 / })
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms))

describe('OrderPad', () => {
  it("labels one button per drink, in the store's order, with the displayed price", () => {
    expect(drinkButtons().map((b) => b.textContent)).toEqual([
      `+1 Bier — ${formatEuro(250)}`,
      `+1 Cola — ${formatEuro(300)}`,
    ])
    expect(screen.getByText('Klaar')).toBeTruthy()
  })

  it('carries the displayed version for the e2e test', () => {
    expect(document.querySelector('[data-quote-version="5"]')).not.toBeNull()
  })

  it('pointer-down, a new tick, then click posts the held price (AC1)', () => {
    fireEvent.pointerDown(bier())
    tick(6, 270)
    expect(bier().textContent).toBe(`+1 Bier — ${formatEuro(250)}`)
    fireEvent.pointerUp(bier())
    fireEvent.click(bier())
    expect(posts).toEqual([
      { quote_version: 5, lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }] },
    ])
  })

  it('a keyboard press holds too (PD10)', () => {
    fireEvent.keyDown(bier(), { key: 'Enter' })
    tick(6, 270)
    fireEvent.click(bier())
    fireEvent.keyUp(bier(), { key: 'Enter' })
    expect(posts[0].lines[0].unit_price_cents).toBe(250)
  })

  it('after 8 s without a quote shows the age, and Ververs promotes (AC6, AC7)', () => {
    fireEvent.pointerDown(bier())
    tick(6, 270)
    advance(AGE_SHOW_MS + 1000)
    expect(screen.getByText(/Prijzen van \d+ s geleden/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ververs' }))
    expect(bier().textContent).toBe(`+1 Bier — ${formatEuro(270)}`)
  })

  it('does not show the age while quotes are fresh', () => {
    advance(AGE_SHOW_MS - 1000)
    expect(screen.queryByText(/Prijzen van/)).toBeNull()
  })

  it('after 15 s disables every button with the message; a fresh tick re-enables them (AC8)', () => {
    advance(STALE_MS + 1000)
    expect(screen.getByText(STALE_TEXT)).toBeTruthy()
    expect(drinkButtons().every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
    tick(6, 270)
    expect(screen.queryByText(STALE_TEXT)).toBeNull()
    expect(drinkButtons().some((b) => (b as HTMLButtonElement).disabled)).toBe(false)
  })

  it('works while offline from a polled snapshot (AC25)', () => {
    advance(STALE_MS + 1000)
    act(() => {
      exchangeStore.setState({ status: 'offline' })
      exchangeStore.setState(
        (s) => applyPolledState(s, snapshotData(9, 280, 310), performance.now()),
        true,
      )
    })
    expect(bier().textContent).toBe(`+1 Bier — ${formatEuro(280)}`)
    fireEvent.click(bier())
    expect(posts[0]).toEqual({
      quote_version: 9,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 280 }],
    })
  })

  it('disables the buttons while a conflict is open (AC14)', async () => {
    controller.dispose()
    controller = createBarController({
      store: exchangeStore,
      now: () => performance.now(),
      setTimeout: (fn, ms) => setTimeout(fn, ms),
      clearTimeout: (id) => clearTimeout(id),
      post: () =>
        Promise.resolve<OrderOutcome>({
          kind: 'price_changed',
          body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
        }),
      uuid: () => crypto.randomUUID(),
    })
    cleanup()
    render(<Harness />)
    fireEvent.click(bier())
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(drinkButtons().every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })
})

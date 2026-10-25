// @vitest-environment jsdom
// OrderPad (Phase 5 T10) over a real controller and the real store, on fake
// timers that include performance.now: SD1, SD4, SD5, SD11, PD10.
// B-06 T12: the basket and "Afrekenen" (SD4, SD5, SD17; AC2, AC5, AC14, AC15, AC17).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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
const STALE_TEXT = 'Geen actuele prijzen — wacht op verbinding'

function snapshotData(
  version: number,
  bier: number,
  cola: number,
  run: typeof RUN = RUN,
): SnapshotData {
  return {
    version,
    run,
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

function config(run: Partial<typeof RUN>, colaActive = true) {
  seq += 1
  dispatch(
    message('config', null, {
      revision: 4,
      run: { ...RUN, ...run, name: 'Vrijmibo' },
      drinks: [
        { drink_id: 1, name: 'Bier', active: true },
        { drink_id: 2, name: 'Cola', active: colaActive },
      ],
      params: {},
    }),
  )
}

let controller: BarController
let posts: OrderBody[]
let answer: (body: OrderBody) => Promise<OrderOutcome>

function Harness() {
  const view = useSyncExternalStore(controller.subscribe, () => controller.view)
  return <OrderPad view={view} actions={controller} />
}

function makeController() {
  return createBarController({
    store: exchangeStore,
    now: () => performance.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    post: ({ body }) => {
      posts.push(body)
      return answer(body)
    },
    newKey: () => crypto.randomUUID(),
  })
}

function receipt(body: OrderBody): OrderOutcome {
  const lines = body.lines.map((l) => ({ ...l, line_total_cents: l.qty * l.unit_price_cents }))
  return {
    kind: 'accepted',
    receipt: {
      order_id: 1,
      version: body.quote_version + 1,
      wall_ts_ms: 0,
      quote_version: body.quote_version,
      lines,
      total_cents: lines.reduce((sum, l) => sum + l.line_total_cents, 0),
      wallet: null,
    },
  }
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'],
  })
  seq = 1
  exchangeStore.setState(initialState, true)
  posts = []
  answer = () => new Promise<OrderOutcome>(() => {})
  controller = makeController()
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

const drinkButtons = () =>
  within(screen.getByRole('group', { name: 'Drankjes' })).getAllByRole('button')
const bier = () => drinkButtons()[0]
const checkout = () => screen.getByRole('button', { name: /^Afrekenen|^Scan eerst/ })
const basketLines = () =>
  screen.queryByRole('list', { name: 'Mandje' }) === null
    ? []
    : within(screen.getByRole('list', { name: 'Mandje' }))
        .getAllByRole('listitem')
        .map((li) => li.querySelector('span')?.textContent)
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms))

describe('OrderPad', () => {
  it("labels one button per drink, in the store's order, with the displayed price", () => {
    expect(drinkButtons().map((b) => b.textContent)).toEqual([
      `Bier — ${formatEuro(250)}`,
      `Cola — ${formatEuro(300)}`,
    ])
    expect(screen.getByText('Klaar')).toBeTruthy()
  })

  it('carries the displayed version for the e2e test', () => {
    expect(document.querySelector('[data-quote-version="5"]')).not.toBeNull()
  })

  it('a tap adds one to the basket and sends nothing; a double tap is 2× (AC17)', () => {
    fireEvent.click(bier())
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
    fireEvent.click(bier())
    fireEvent.click(drinkButtons()[1])
    expect(basketLines()).toEqual([`2× Bier — ${formatEuro(500)}`, `1× Cola — ${formatEuro(300)}`])
    expect(posts).toEqual([])
    expect(checkout().textContent).toBe(`Afrekenen zonder wallet ${formatEuro(800)}`)
  })

  it('"−" takes one off, and "Leegmaken" empties the basket (AC17)', () => {
    fireEvent.click(bier())
    fireEvent.click(bier())
    fireEvent.click(screen.getByRole('button', { name: 'Eén Bier minder' }))
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
    fireEvent.click(screen.getByRole('button', { name: 'Leegmaken' }))
    expect(basketLines()).toEqual([])
    expect((checkout() as HTMLButtonElement).disabled).toBe(true)
  })

  it('with the switch off, "Afrekenen zonder wallet" posts the basket at the displayed version (AC5, AC15)', () => {
    fireEvent.click(bier())
    fireEvent.click(bier())
    fireEvent.click(drinkButtons()[1])
    fireEvent.click(checkout())
    expect(posts).toEqual([
      {
        quote_version: 5,
        lines: [
          { drink_id: 1, qty: 2, unit_price_cents: 250 },
          { drink_id: 2, qty: 1, unit_price_cents: 300 },
        ],
      },
    ])
  })

  it('pointer-down on a drink, a new tick, then "Afrekenen" posts the held price (AC1)', () => {
    fireEvent.pointerDown(bier())
    tick(6, 270)
    expect(bier().textContent).toBe(`Bier — ${formatEuro(250)}`)
    fireEvent.pointerUp(bier())
    fireEvent.click(bier())
    fireEvent.pointerDown(checkout())
    fireEvent.pointerUp(checkout())
    fireEvent.click(checkout())
    expect(posts).toEqual([
      { quote_version: 5, lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }] },
    ])
  })

  it('a keyboard press holds too (PD10)', () => {
    fireEvent.keyDown(bier(), { key: 'Enter' })
    tick(6, 270)
    fireEvent.click(bier())
    fireEvent.keyUp(bier(), { key: 'Enter' })
    fireEvent.click(checkout())
    expect(posts[0].lines[0].unit_price_cents).toBe(250)
  })

  it('with the switch on, "Afrekenen" is disabled with "Scan eerst een wallet" (AC14)', () => {
    dispatch(message('snapshot', 6, snapshotData(6, 250, 300, { ...RUN, wallet_required: true })))
    fireEvent.click(bier())
    expect(checkout().textContent).toBe('Scan eerst een wallet')
    expect((checkout() as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(checkout())
    expect(posts).toEqual([])
  })

  it('a config message turning the switch on changes the button without a reload (AC2)', () => {
    fireEvent.click(bier())
    expect(checkout().textContent).toBe(`Afrekenen zonder wallet ${formatEuro(250)}`)
    config({ wallet_required: true })
    expect(checkout().textContent).toBe('Scan eerst een wallet')
    config({ wallet_required: false })
    expect((checkout() as HTMLButtonElement).disabled).toBe(false)
  })

  it('the basket clears on a 201 and stays on a 409 (SD6, AC11)', async () => {
    answer = (body) =>
      Promise.resolve<OrderOutcome>(
        body.quote_version === 5
          ? {
              kind: 'price_changed',
              body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
            }
          : receipt(body),
      )
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
    expect(controller.view.headConflict).not.toBeNull()
    act(() => controller.confirm())
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(basketLines()).toEqual([])
  })

  it('after 8 s without a quote shows the age, and Ververs promotes (AC6, AC7)', () => {
    fireEvent.pointerDown(bier())
    tick(6, 270)
    advance(AGE_SHOW_MS + 1000)
    expect(screen.getByText(/Prijzen van \d+ s geleden/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ververs' }))
    expect(bier().textContent).toBe(`Bier — ${formatEuro(270)}`)
  })

  it('does not show the age while quotes are fresh', () => {
    advance(AGE_SHOW_MS - 1000)
    expect(screen.queryByText(/Prijzen van/)).toBeNull()
  })

  it('after 15 s disables every button with the message; a fresh tick re-enables them (AC8)', () => {
    fireEvent.click(bier())
    advance(STALE_MS + 1000)
    expect(screen.getByText(STALE_TEXT)).toBeTruthy()
    expect(drinkButtons().every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
    expect((checkout() as HTMLButtonElement).disabled).toBe(true)
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
    expect(bier().textContent).toBe(`Bier — ${formatEuro(280)}`)
    fireEvent.click(bier())
    fireEvent.click(checkout())
    expect(posts[0]).toEqual({
      quote_version: 9,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 280 }],
    })
  })

  it('disables the buttons while a conflict is open (AC14)', async () => {
    answer = () =>
      Promise.resolve<OrderOutcome>({
        kind: 'price_changed',
        body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
      })
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(drinkButtons().every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
    expect((checkout() as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('removed drinks (Phase 6 T37: SD18; AC23)', () => {
  it('a config removing a drink removes its button', () => {
    expect(drinkButtons()).toHaveLength(2)
    config({}, false)
    expect(drinkButtons().map((b) => b.textContent)).toEqual([expect.stringContaining('Bier')])
  })
})

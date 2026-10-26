// @vitest-environment jsdom
// OrderPad (Phase 5 T10) over a real controller and the real store, on fake
// timers that include performance.now: SD1, SD4, SD5, SD11, PD10.
// B-06 T12: the basket and "Afrekenen" (SD4, SD5, SD17; AC2, AC5, AC14, AC15, AC17).
// B-06 T13: the held wallet and paying (SD4-SD7, SD18; AC5, AC11-AC14, AC18, AC25).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatBalance, formatEuro } from '../../lib/format'
import { HttpError } from '../../lib/http'
import {
  applyMessage,
  applyPolledState,
  exchangeStore,
  initialState,
  type ServerMessage,
  type SnapshotData,
} from '../exchange'
import type { OrderBody, OrderOutcome } from './api/orders'
import { createBarController, type BarController, type HeldWallet } from './model/barController'
import { AGE_SHOW_MS, STALE_MS } from './model/constants'
import { OrderPad } from './OrderPad'
import { PendingOrders } from './PendingOrders'

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
let keys: string[]
let answer: (body: OrderBody) => Promise<OrderOutcome>

function Harness() {
  const view = useSyncExternalStore(controller.subscribe, () => controller.view)
  return (
    <>
      <OrderPad view={view} actions={controller} />
      <PendingOrders view={view} actions={controller} />
    </>
  )
}

function makeController() {
  return createBarController({
    store: exchangeStore,
    now: () => performance.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    post: ({ key, body }) => {
      posts.push(body)
      keys.push(key)
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
  keys = []
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
const checkout = () => screen.getByRole('button', { name: /^Afrekenen|^Scan eerst|^Saldo/ })
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

describe('the held wallet (B-06 T13)', () => {
  const JAN: HeldWallet = { query: { short_code: 'K7MQ-X2P9' }, name: 'Jan', balance_cents: 1500 }
  const hold = (wallet: HeldWallet = JAN) => act(() => controller.hold(wallet))
  const held = () => screen.queryByRole('region', { name: 'Wallet' })
  const settle = () => act(() => vi.advanceTimersByTimeAsync(0))
  /** A leaf whose text is `text` exactly: no-break spaces kept (the default matcher folds them). */
  const exactly = (text: string) => (_: string, el: Element | null) =>
    el?.children.length === 0 && el.textContent === text

  it('shows the name large and the balance, in place of the picker (AC4, SD13)', () => {
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
    hold()
    expect(held()?.querySelector('strong')?.textContent).toBe('Jan')
    expect(held()?.textContent).toContain(`saldo ${formatEuro(1500)}`)
    expect(screen.queryByLabelText('Code typen')).toBeNull()
  })

  it('a negative balance shows with a minus (AC25)', () => {
    hold({ ...JAN, balance_cents: -90 })
    expect(held()?.textContent).toContain('saldo −€\u00a00,90')
  })

  it('"Afrekenen €T" posts the basket with the wallet as scanned (AC5)', () => {
    hold()
    fireEvent.click(bier())
    expect(checkout().textContent).toBe(`Afrekenen ${formatEuro(250)}`)
    fireEvent.click(checkout())
    expect(posts).toEqual([
      {
        quote_version: 5,
        lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250 }],
        wallet: { short_code: 'K7MQ-X2P9' },
      },
    ])
  })

  it('with the switch on, a held wallet enables "Afrekenen" (AC14)', () => {
    config({ wallet_required: true })
    fireEvent.click(bier())
    expect(checkout().textContent).toBe('Scan eerst een wallet')
    hold()
    expect(checkout().textContent).toBe(`Afrekenen ${formatEuro(250)}`)
    expect((checkout() as HTMLButtonElement).disabled).toBe(false)
  })

  it('a 409 confirm carries the same wallet and a new key (AC11)', async () => {
    answer = (body) =>
      body.quote_version === 5
        ? Promise.resolve<OrderOutcome>({
            kind: 'price_changed',
            body: { version: 6, prices: [{ drink_id: 1, price_cents: 260 }] },
          })
        : new Promise<OrderOutcome>(() => {})
    hold()
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await settle()
    act(() => controller.confirm())
    expect(posts[1]).toEqual({
      quote_version: 6,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 260 }],
      wallet: { short_code: 'K7MQ-X2P9' },
    })
    expect(keys[1]).not.toBe(keys[0])
  })

  it('a 404 says "Onbekende wallet", clears the wallet and keeps the basket (AC12)', async () => {
    answer = () => Promise.reject(new HttpError(404, 'wallet_not_found', 'no'))
    hold()
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await settle()
    expect(screen.getByText('Onbekende wallet')).toBeTruthy()
    expect(held()).toBeNull()
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
  })

  it('a total over balance + limit disables "Afrekenen" with the shortfall (AC18)', () => {
    hold({ ...JAN, balance_cents: 100 })
    fireEvent.click(bier())
    expect(checkout().textContent).toBe(`Saldo ${formatEuro(100)} — nog ${formatEuro(150)} tekort`)
    expect((checkout() as HTMLButtonElement).disabled).toBe(true)
    config({ credit_limit_cents: 150 })
    expect(checkout().textContent).toBe(`Afrekenen ${formatEuro(250)}`)
    expect((checkout() as HTMLButtonElement).disabled).toBe(false)
  })

  it("a 409 insufficient_balance shows the server's shortfall and updates the balance (SD18)", async () => {
    answer = () =>
      Promise.reject(
        new HttpError(409, 'insufficient_balance', 'no', {
          balance_cents: 100,
          credit_limit_cents: 0,
        }),
      )
    hold()
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await settle()
    const shortfall = `Saldo ${formatEuro(100)} — nog ${formatEuro(150)} tekort`
    expect(screen.getAllByText(exactly(shortfall))).toHaveLength(2) // the answer, and the button
    expect(held()?.textContent).toContain(`saldo ${formatEuro(100)}`)
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
  })

  it('a paid order says so from the receipt, clears both, and the text goes after 3 s (AC13)', async () => {
    answer = (body) => {
      const paid = receipt(body)
      if (paid.kind !== 'accepted') throw new Error('a receipt')
      const wallet = { name: 'Jan', balance_after_cents: -90 }
      return Promise.resolve<OrderOutcome>({ ...paid, receipt: { ...paid.receipt, wallet } })
    }
    config({ credit_limit_cents: 250 })
    hold({ ...JAN, balance_cents: 160 })
    fireEvent.click(bier())
    fireEvent.click(checkout())
    await settle()
    const paid = `Betaald ${formatEuro(250)} — Jan, saldo ${formatBalance(-90)}`
    expect(screen.getByText(exactly(paid))).toBeTruthy()
    expect(held()).toBeNull()
    expect(basketLines()).toEqual([])
    advance(3000)
    expect(screen.queryByText(exactly(paid))).toBeNull()
  })

  it('"Andere wallet" lets go of the wallet only, "Annuleren" of both (T14, AC19)', () => {
    hold()
    fireEvent.click(bier())
    fireEvent.click(screen.getByRole('button', { name: 'Andere wallet' }))
    expect(held()).toBeNull()
    expect(basketLines()).toEqual([`1× Bier — ${formatEuro(250)}`])
    hold()
    fireEvent.click(within(held()!).getByRole('button', { name: 'Annuleren' }))
    expect(held()).toBeNull()
    expect(basketLines()).toEqual([])
  })

  it('while the order is open the held wallet cannot be replaced (PD12)', () => {
    hold()
    fireEvent.click(bier())
    fireEvent.click(checkout())
    hold({ ...JAN, name: 'Piet' })
    expect(held()?.querySelector('strong')?.textContent).toBe('Jan')
  })
})

describe('removed drinks (Phase 6 T37: SD18; AC23)', () => {
  it('a config removing a drink removes its button', () => {
    expect(drinkButtons()).toHaveLength(2)
    config({}, false)
    expect(drinkButtons().map((b) => b.textContent)).toEqual([expect.stringContaining('Bier')])
  })
})

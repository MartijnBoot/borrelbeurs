// @vitest-environment jsdom
// PendingOrders and OrderConflict (Phase 5 T11) over a real controller and
// the real store, fake timers, a scripted transport: SD8-SD10, PD7. B-06 T12: an
// order is a basket (SD4, SD7; AC11).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '../../lib/http'
import { formatEuro } from '../../lib/format'
import {
  applyMessage,
  exchangeStore,
  initialState,
  type ServerMessage,
  type SnapshotData,
} from '../exchange'
import type { OrderBody, OrderOutcome } from './api/orders'
import { createBarController, type BarController } from './model/barController'
import { CONFIRM_GUARD_MS } from './model/constants'
import { LINGER_MS, RETRY_DELAYS_MS } from './model/orderIntents'
import { OrderConflict } from './OrderConflict'
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

const SNAPSHOT: SnapshotData = {
  version: 5,
  run: RUN,
  drinks: [
    { drink_id: 1, name: 'Bier', active: true },
    { drink_id: 2, name: 'Cola', active: true },
  ],
  params: {},
  prices: {
    1: { price_cents: 250, chart_price_cents: 250 },
    2: { price_cents: 300, chart_price_cents: 300 },
  },
  bars: {},
  news: [],
  earnings: {},
  market_events: [],
}

function message(type: ServerMessage['type'], version: number | null, data: unknown) {
  return { v: 1, type, seq: 1, ts_ms: 0, run_id: 1, version, data } as ServerMessage
}

interface Call {
  key: string
  body: OrderBody
  resolve(o: OrderOutcome): void
  reject(e: unknown): void
}

let controller: BarController
let calls: Call[]

function Harness() {
  const view = useSyncExternalStore(controller.subscribe, () => controller.view)
  return (
    <>
      <PendingOrders view={view} actions={controller} />
      <OrderConflict view={view} actions={controller} />
    </>
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  exchangeStore.setState(initialState, true)
  calls = []
  controller = createBarController({
    store: exchangeStore,
    now: () => Date.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    post: ({ key, body }) =>
      new Promise<OrderOutcome>((resolve, reject) => calls.push({ key, body, resolve, reject })),
    newKey: () => crypto.randomUUID(),
  })
  const hello = {
    boot_id: 'B',
    run_id: 1,
    tick_interval_ms: 1000,
    protocol: 1,
    role: 'bar',
    theme: THEME,
  }
  act(() => {
    exchangeStore.setState((s) => applyMessage(s, message('hello', null, hello), Date.now()), true)
    exchangeStore.setState(
      (s) => applyMessage(s, message('snapshot', 5, SNAPSHOT), Date.now()),
      true,
    )
  })
  render(<Harness />)
})

afterEach(() => {
  cleanup()
  controller.dispose()
  vi.useRealTimers()
})

/** B-06: the drinks into the basket, then "Afrekenen". */
const buy = (...drinkIds: number[]) =>
  act(() => {
    for (const id of drinkIds) controller.add(id)
    controller.checkout()
  })
const settle = () => act(() => vi.advanceTimersByTimeAsync(0))
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

function receipt(body: OrderBody, cents?: number): OrderOutcome {
  const lines = body.lines.map((l, i) => {
    const unit = i === 0 && cents !== undefined ? cents : l.unit_price_cents
    return { ...l, unit_price_cents: unit, line_total_cents: l.qty * unit }
  })
  return {
    kind: 'accepted',
    receipt: {
      order_id: 1,
      version: 6,
      wall_ts_ms: 0,
      quote_version: body.quote_version,
      lines,
      total_cents: lines.reduce((sum, l) => sum + l.line_total_cents, 0),
      wallet: null,
    },
  }
}

function priceChanged(version: number, prices: Record<number, number>): OrderOutcome {
  return {
    kind: 'price_changed',
    body: {
      version,
      prices: Object.entries(prices).map(([d, c]) => ({ drink_id: Number(d), price_cents: c })),
    },
  }
}

describe('PendingOrders', () => {
  it('shows an in-flight order as bezig… (AC16)', () => {
    buy(1)
    expect(screen.getByText('1× Bier — bezig…')).toBeTruthy()
  })

  it('names every line of a basket (B-06 SD7)', () => {
    buy(1, 1, 2)
    expect(screen.getByText('2× Bier, 1× Cola — bezig…')).toBeTruthy()
  })

  it("shows a 201 with the receipt's total for 3 s, then drops it (AC3, PD7)", async () => {
    buy(1, 2)
    calls[0].resolve(receipt(calls[0].body, 260))
    await settle()
    expect(screen.getByRole('listitem').textContent).toBe(
      `1× Bier, 1× Cola besteld — ${formatEuro(560)}`,
    )
    await advance(LINGER_MS)
    expect(screen.queryByText(/besteld/)).toBeNull()
  })

  it('after the retries shows Onbekend; Opnieuw re-posts the same key; Sluiten warns (AC11)', async () => {
    buy(1)
    for (let i = 0; i < 4; i++) {
      calls[i].reject(new TypeError('Failed to fetch'))
      await settle()
      if (i < 3) await advance(RETRY_DELAYS_MS[i])
    }
    expect(screen.getByText('Onbekend')).toBeTruthy()
    expect(screen.getByText('1× Bier: niet bevestigd — opnieuw proberen?')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Opnieuw' }))
    expect(calls).toHaveLength(5)
    expect(calls[4].key).toBe(calls[0].key)
    calls[4].reject(new TypeError('Failed to fetch'))
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(screen.getByText('Mogelijk toch geboekt — controleer de omzet')).toBeTruthy()
    await advance(LINGER_MS)
    expect(screen.queryByText(/Mogelijk toch geboekt/)).toBeNull()
  })

  it('shows a 422 as Fout bij bestellen after exactly one post (AC15)', async () => {
    buy(1)
    calls[0].reject(new HttpError(422, 'invalid_order', 'nope'))
    await settle()
    expect(screen.getByText(/Fout bij bestellen/)).toBeTruthy()
    await advance(60_000)
    expect(calls).toHaveLength(1)
  })

  it('shows a 409 wallet_required as "Scan eerst een wallet" (B-06 AC14)', async () => {
    buy(1)
    calls[0].reject(new HttpError(409, 'wallet_required', 'scan one'))
    await settle()
    expect(screen.getByRole('listitem').textContent).toBe('Scan eerst een wallet')
  })
})

describe('a removed drink (Phase 6 T37: SD13; AC19)', () => {
  it('a 422 drink_unavailable shows "… niet meer beschikbaar" for 3 s', async () => {
    buy(1)
    calls[0].reject(new HttpError(422, 'drink_unavailable', 'removed'))
    await settle()
    expect(screen.getByText('1× Bier: niet meer beschikbaar')).toBeTruthy()
    await advance(LINGER_MS)
    expect(screen.queryByText(/niet meer beschikbaar/)).toBeNull()
    expect(calls).toHaveLength(1)
  })
})

describe('OrderConflict', () => {
  it("lists each changed line at the 409's prices and the new total (B-06 AC11)", async () => {
    buy(1, 1, 2)
    calls[0].resolve(priceChanged(9, { 1: 270, 2: 300 }))
    await settle()
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Prijzen zijn veranderd:')
    const changes = [...dialog.querySelectorAll('li')].map((li) => li.textContent)
    expect(changes).toEqual([`Bier: ${formatEuro(250)} → ${formatEuro(270)}`])
    expect(dialog.textContent).toContain(`Nieuw totaal: ${formatEuro(840)}`)
  })

  it('Bevestigen posts a new key with the same lines at exactly the 409 prices (AC12, AC13)', async () => {
    buy(1, 2)
    calls[0].resolve(priceChanged(9, { 1: 270, 2: 310 }))
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(calls).toHaveLength(2)
    expect(calls[1].key).not.toBe(calls[0].key)
    expect(calls[1].body).toEqual({
      quote_version: 9,
      lines: [
        { drink_id: 1, qty: 1, unit_price_cents: 270 },
        { drink_id: 2, qty: 1, unit_price_cents: 310 },
      ],
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('Annuleren posts nothing, shows Geannuleerd and keeps the basket (AC11, AC13)', async () => {
    buy(1)
    calls[0].resolve(priceChanged(9, { 1: 270 }))
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(calls).toHaveLength(1)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText(/Geannuleerd/)).toBeTruthy()
    expect(controller.view.basket).toEqual([{ drinkId: 1, qty: 1 }])
  })

  it('a second tap right after a Bevestigen cannot confirm the next conflict unread (AC14)', async () => {
    buy(1)
    calls[0].resolve(priceChanged(9, { 1: 270 }))
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(calls).toHaveLength(2)
    calls[1].resolve(priceChanged(10, { 1: 280 }))
    await settle()
    expect(screen.getByRole('dialog').textContent).toContain(formatEuro(280))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' })) // the double tap
    expect(calls).toHaveLength(2)
    await advance(CONFIRM_GUARD_MS)
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(calls).toHaveLength(3)
    expect(calls[2].body.lines[0].unit_price_cents).toBe(280)
  })
})

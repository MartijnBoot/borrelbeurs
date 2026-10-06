// @vitest-environment jsdom
// PendingOrders and OrderConflict (Phase 5 T11) over a real controller and
// the real store, fake timers, a scripted transport: SD8-SD10, PD7.
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
import { LINGER_MS, RETRY_DELAYS_MS } from './model/orderIntents'
import { OrderConflict } from './OrderConflict'
import { PendingOrders } from './PendingOrders'

const THEME = { preset: 'blauw' as const, revision: 0, tokens: {}, font_family: 'sans-serif' }
const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
}

const SNAPSHOT: SnapshotData = {
  version: 5,
  run: RUN,
  drinks: [
    { drink_id: 1, name: 'Bier' },
    { drink_id: 2, name: 'Cola' },
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

const tap = (drinkId: number) => act(() => void controller.tap(drinkId))
const settle = () => act(() => vi.advanceTimersByTimeAsync(0))
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

function receipt(body: OrderBody, cents: number): OrderOutcome {
  const { drink_id } = body.lines[0]
  return {
    kind: 'accepted',
    receipt: {
      order_id: 1,
      version: 6,
      wall_ts_ms: 0,
      quote_version: body.quote_version,
      lines: [{ drink_id, qty: 1, unit_price_cents: cents, line_total_cents: cents }],
      total_cents: cents,
    },
  }
}

function priceChanged(drinkId: number, cents: number): OrderOutcome {
  return {
    kind: 'price_changed',
    body: { version: 9, prices: [{ drink_id: drinkId, price_cents: cents }] },
  }
}

describe('PendingOrders', () => {
  it('shows an in-flight order as bezig… (AC16)', () => {
    tap(1)
    expect(screen.getByText('1× Bier — bezig…')).toBeTruthy()
  })

  it("shows a 201 with the receipt's price for 3 s, then drops it (AC3, PD7)", async () => {
    tap(1)
    calls[0].resolve(receipt(calls[0].body, 260))
    await settle()
    expect(screen.getByRole('listitem').textContent).toBe(`1× Bier besteld — ${formatEuro(260)}`)
    await advance(LINGER_MS)
    expect(screen.queryByText(/Bier besteld/)).toBeNull()
  })

  it('after the retries shows Onbekend; Opnieuw re-posts the same key; Sluiten warns (AC11)', async () => {
    tap(1)
    for (let i = 0; i < 4; i++) {
      calls[i].reject(new TypeError('Failed to fetch'))
      await settle()
      if (i < 3) await advance(RETRY_DELAYS_MS[i])
    }
    expect(screen.getByText('Onbekend')).toBeTruthy()
    expect(screen.getByText('Bier: niet bevestigd — opnieuw proberen?')).toBeTruthy()

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
    tap(1)
    calls[0].reject(new HttpError(422, 'invalid_order', 'nope'))
    await settle()
    expect(screen.getByText(/Fout bij bestellen/)).toBeTruthy()
    await advance(60_000)
    expect(calls).toHaveLength(1)
  })
})

describe('OrderConflict', () => {
  it("shows the 409's price; Bevestigen posts a new key at exactly that price (AC12, AC13)", async () => {
    tap(1)
    calls[0].resolve(priceChanged(1, 270))
    await settle()
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain(`Bier: prijs is nu ${formatEuro(270)} — bevestigen?`)
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(calls).toHaveLength(2)
    expect(calls[1].key).not.toBe(calls[0].key)
    expect(calls[1].body).toEqual({
      quote_version: 9,
      lines: [{ drink_id: 1, qty: 1, unit_price_cents: 270 }],
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('Annuleren posts nothing and shows Geannuleerd (AC13)', async () => {
    tap(1)
    calls[0].resolve(priceChanged(1, 270))
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(calls).toHaveLength(1)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText(/Geannuleerd/)).toBeTruthy()
  })

  it('two 409s show one dialog, then the next (AC14)', async () => {
    tap(1)
    tap(2)
    calls[1].resolve(priceChanged(2, 310))
    calls[0].resolve(priceChanged(1, 270))
    await settle()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(screen.getByRole('dialog').textContent).toContain('Bier: prijs is nu')
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `Cola: prijs is nu ${formatEuro(310)} — bevestigen?`,
    )
  })
})

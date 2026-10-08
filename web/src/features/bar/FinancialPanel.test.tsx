// @vitest-environment jsdom
// FinancialPanel (Phase 5 T12, SD15): the server's aggregates, nothing else.
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { formatEuro } from '../../lib/format'
import {
  applyMessage,
  exchangeStore,
  initialState,
  type ServerMessage,
  type SnapshotData,
} from '../exchange'
import { FinancialPanel } from './FinancialPanel'

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
}

function snapshot(earnings: SnapshotData['earnings']): SnapshotData {
  return {
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
    earnings,
    market_events: [],
  }
}

let seq = 1
function dispatch(type: ServerMessage['type'], data: unknown, version: number | null = 5) {
  const message = { v: 1, type, seq, ts_ms: 0, run_id: 1, version, data } as ServerMessage
  act(() => exchangeStore.setState((s) => applyMessage(s, message, 0), true))
}

function order(drinkId: number, qty: number, revenue: number) {
  seq += 1
  const price = { price_cents: 250, chart_price_cents: 250 }
  dispatch('order', {
    order_id: seq,
    lines: [{ drink_id: drinkId, qty, unit_price_cents: 1, line_total_cents: revenue }],
    total_cents: revenue,
    earnings_delta: { [drinkId]: { qty, revenue_cents: revenue } },
    prices: { 1: price, 2: price },
  })
}

beforeEach(() => {
  seq = 1
  exchangeStore.setState(initialState, true)
  const hello = {
    boot_id: 'B',
    run_id: 1,
    tick_interval_ms: 1000,
    protocol: 1,
    role: 'bar',
    theme: THEME,
  }
  dispatch('hello', hello, null)
  dispatch('snapshot', snapshot({ 1: { qty: 2, revenue_cents: 520 } }))
  render(<FinancialPanel />)
})

afterEach(cleanup)

const text = () => document.body.textContent ?? ''
const testId = (id: string) => screen.getByTestId(id).textContent

describe('FinancialPanel', () => {
  it("renders the snapshot's aggregates exactly", () => {
    expect(screen.getByText('💶 Financieel overzicht')).toBeTruthy()
    expect(testId('total-revenue')).toBe(formatEuro(520))
    expect(testId('total-qty')).toBe('2')
    expect(text()).toContain(`Bier: 2× — ${formatEuro(520)}`)
    expect(text()).toContain(`Cola: 0× — ${formatEuro(0)}`)
  })

  it("adds an order's delta (AC19)", () => {
    order(2, 1, 300)
    expect(testId('total-revenue')).toBe(formatEuro(820))
    expect(testId('total-qty')).toBe('3')
    expect(text()).toContain(`Cola: 1× — ${formatEuro(300)}`)
  })

  it('a later snapshot replaces the totals (AC18)', () => {
    order(2, 1, 300)
    dispatch('snapshot', snapshot({ 1: { qty: 1, revenue_cents: 100 } }))
    expect(testId('total-revenue')).toBe(formatEuro(100))
    expect(testId('total-qty')).toBe('1')
  })

  it('does not move on unrelated store changes, such as a pending tap elsewhere (AC16)', () => {
    const before = text()
    act(() => exchangeStore.setState({ status: 'offline' }))
    order(1, 0, 0) // an order message that carries no sale changes nothing either
    expect(text()).toBe(before)
  })

  it('shows no bar-price figures, sales count or download (SD15)', () => {
    expect(text().toLowerCase()).not.toContain('bar prijs')
    expect(text().toLowerCase()).not.toContain('verkopen')
    expect(text()).not.toContain('Download')
  })
})

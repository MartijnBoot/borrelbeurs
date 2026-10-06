// @vitest-environment jsdom
// BarPage (Phase 5 T15): the layout and the empty state (SD14, SD18, AC27).
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyMessage, exchangeStore, type ServerMessage, type SnapshotData } from '../exchange'
import { BarPage } from './BarPage'

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
  drinks: [{ drink_id: 1, name: 'Bier' }],
  params: {},
  prices: { 1: { price_cents: 250, chart_price_cents: 250 } },
  bars: {},
  news: [],
  earnings: {},
  market_events: [],
}

function dispatch(type: ServerMessage['type'], data: unknown, version: number | null = 5) {
  const message = { v: 1, type, seq: 1, ts_ms: 0, run_id: 1, version, data } as ServerMessage
  act(() => exchangeStore.setState((s) => applyMessage(s, message, performance.now()), true))
}

const hello = (runId: number | null) => ({
  boot_id: 'B',
  run_id: runId,
  tick_interval_ms: 1000,
  protocol: 1,
  role: 'bar',
  theme: THEME,
})

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  // Narrow: the revenue chart is not constructed, so jsdom needs no canvas.
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const drinkButtons = () => screen.queryAllByRole('button', { name: /^\+1 / })

describe('BarPage', () => {
  it('with no live run shows only "Geen actieve borrel"; a snapshot shows the pad without remount (AC27)', () => {
    dispatch('hello', hello(null), null)
    render(<BarPage />)
    const header = screen.getByRole('heading', { name: '🍺 Bar — Bestellen' })
    expect(screen.getByText('Geen actieve borrel')).toBeTruthy()
    expect(drinkButtons()).toHaveLength(0)
    expect(screen.queryByText('💶 Financieel overzicht')).toBeNull()

    dispatch('snapshot', SNAPSHOT)
    expect(screen.queryByText('Geen actieve borrel')).toBeNull()
    expect(drinkButtons()).toHaveLength(1)
    expect(screen.getByRole('heading', { name: '🍺 Bar — Bestellen' })).toBe(header)
  })

  it('with a live run renders both cards', () => {
    dispatch('hello', hello(1), null)
    dispatch('snapshot', SNAPSHOT)
    render(<BarPage />)
    expect(screen.getByRole('heading', { name: 'Bestellingen' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '💶 Financieel overzicht' })).toBeTruthy()
    expect(drinkButtons()).toHaveLength(1)
    expect(screen.getByText('Klaar')).toBeTruthy()
  })
})

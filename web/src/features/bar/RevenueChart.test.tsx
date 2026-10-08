// @vitest-environment jsdom
// RevenueChart against a mocked lightweight-charts whose `update` throws on
// an older time, like the real library (Phase 5 T14): AC16, AC21-AC24.
import { act, cleanup, render } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ExchangeState, type ThemeData } from '../exchange'
import { fetchEarningsSeries } from './api/earningsSeries'
import type { RevenuePoint } from './model/revenueSeries'
import { RevenueChart } from './RevenueChart'

interface FakeSeries {
  setData: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  last: number | null
}

interface FakeChart {
  options: unknown
  series: FakeSeries[]
  applyOptions: ReturnType<typeof vi.fn>
  remove: ReturnType<typeof vi.fn>
}

const charts: FakeChart[] = []

vi.mock('lightweight-charts', () => ({
  LineSeries: { type: 'Line' },
  CrosshairMode: { Hidden: 2 },
  createChart: vi.fn((_el: HTMLElement, options: unknown) => {
    const chart = {
      options,
      series: [] as FakeSeries[],
      addSeries: vi.fn(() => {
        const series: FakeSeries = {
          last: null,
          setData: vi.fn((data: { time: number }[]) => {
            series.last = data.at(-1)?.time ?? null
          }),
          update: vi.fn((point: { time: number }) => {
            if (series.last !== null && point.time < series.last) {
              throw new Error('Cannot update oldest data')
            }
            series.last = point.time
          }),
          applyOptions: vi.fn(),
        }
        chart.series.push(series)
        return series
      }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
      timeScale: () => ({ fitContent: () => {} }),
    }
    charts.push(chart)
    return chart
  }),
}))

vi.mock('./api/earningsSeries', () => ({ fetchEarningsSeries: vi.fn() }))
const fetchMock = vi.mocked(fetchEarningsSeries)

const HISTORY: RevenuePoint[] = [
  { t_ms: 60_000, cum_revenue_cents: 250 },
  { t_ms: 120_000, cum_revenue_cents: 770 },
]

const theme = (revision: number, accent: string): ThemeData => ({
  preset: 'blauw',
  revision,
  tokens: {
    '--grid': '#1a2744',
    '--muted': '#9aa7bd',
    '--input-bg': '#0a1426',
    '--accent': accent,
  },
  font_family: 'Inter',
  images: { bg: null, header: null, logo: null, promo: null },
})

let narrow = false

function setStore(patch: Partial<ExchangeState>) {
  act(() => exchangeStore.setState(patch))
}

/** An applied order: the server's earnings grow and `lastOrderTsMs` moves. */
function order(tsMs: number, revenueCents: number) {
  setStore({ earnings: { 1: { qty: 1, revenue_cents: revenueCents } }, lastOrderTsMs: tsMs })
}

const flush = () => act(() => Promise.resolve())
const series = () => charts[0].series[0]

beforeEach(() => {
  charts.length = 0
  narrow = false
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(HISTORY)
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: narrow && query === '(max-width: 640px)',
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  exchangeStore.setState(
    { ...exchangeStore.getInitialState(), snapshotGen: 1, theme: theme(1, '#38bdf8') },
    true,
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('RevenueChart', () => {
  it('fetches on mount and sets the history once', async () => {
    render(<RevenueChart />)
    await flush()
    expect(charts).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(series().setData).toHaveBeenCalledTimes(1)
    expect(series().setData).toHaveBeenCalledWith([
      { time: 60, value: 250 },
      { time: 120, value: 770 },
    ])
  })

  it('two orders give two updates and no setData (AC22)', async () => {
    render(<RevenueChart />)
    await flush()
    order(130_500, 1_020)
    order(140_200, 1_290)
    expect(series().setData).toHaveBeenCalledTimes(1)
    expect(series().update.mock.calls).toEqual([
      [{ time: 130, value: 1_020 }],
      [{ time: 140, value: 1_290 }],
    ])
  })

  it('two orders in one second give no throw (AC21)', async () => {
    render(<RevenueChart />)
    await flush()
    order(130_100, 1_020)
    order(130_900, 1_290)
    expect(series().update).toHaveBeenLastCalledWith({ time: 130, value: 1_290 })
  })

  it('an order inside the last history bucket updates that last point, never backwards (AC21, AC22)', async () => {
    render(<RevenueChart />)
    await flush()
    order(100_000, 600) // before the bucket end at 120 s
    expect(series().setData).toHaveBeenCalledTimes(1)
    expect(series().update).toHaveBeenLastCalledWith({ time: 120, value: 600 })
    order(110_000, 700)
    expect(series().setData).toHaveBeenCalledTimes(1)
    expect(series().update).toHaveBeenLastCalledWith({ time: 120, value: 700 })
    order(125_000, 800) // past the bucket end: a new point
    expect(series().update).toHaveBeenLastCalledWith({ time: 125, value: 800 })
  })

  it('a snapshot refetches and sets the data again', async () => {
    render(<RevenueChart />)
    await flush()
    setStore({ snapshotGen: 2, lastOrderTsMs: null })
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(series().setData).toHaveBeenCalledTimes(2)
  })

  it('a store change that is not an order does not move the chart (AC16)', async () => {
    render(<RevenueChart />)
    await flush()
    setStore({ status: 'offline' })
    expect(series().update).not.toHaveBeenCalled()
    expect(series().setData).toHaveBeenCalledTimes(1)
  })

  it('a theme change applies the tokens without a new chart (AC23)', async () => {
    render(<RevenueChart />)
    await flush()
    setStore({ theme: theme(2, '#ff0000') })
    expect(charts).toHaveLength(1)
    expect(charts[0].applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ grid: expect.anything() }),
    )
    expect(series().applyOptions).toHaveBeenLastCalledWith({ color: '#ff0000' })
  })

  it('removes the chart exactly once per mount under StrictMode, and ignores a late fetch (AC22)', async () => {
    let resolve: (points: RevenuePoint[]) => void = () => {}
    fetchMock.mockImplementation(() => new Promise((r) => (resolve = r)))
    const { unmount } = render(
      <StrictMode>
        <RevenueChart />
      </StrictMode>,
    )
    unmount()
    for (const chart of charts) expect(chart.remove).toHaveBeenCalledTimes(1)
    resolve(HISTORY)
    await flush()
    for (const chart of charts) expect(chart.series[0].setData).not.toHaveBeenCalled()
  })

  it('at ≤640 px constructs no chart and fetches nothing (AC24)', async () => {
    narrow = true
    render(<RevenueChart />)
    await flush()
    expect(charts).toHaveLength(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

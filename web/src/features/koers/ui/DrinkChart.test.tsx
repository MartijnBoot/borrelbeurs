// @vitest-environment jsdom
// The chart host against a mocked lightweight-charts (T19): a stable host,
// fed imperatively from the store (AC11, AC12, AC27-AC29, AC35).
import { act, cleanup, render } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  exchangeStore,
  smaSeries,
  type Bar,
  type ExchangeState,
  type ThemeData,
} from '../../exchange'
import { DrinkChart } from './DrinkChart'

interface FakeSeries {
  kind: string
  setData: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
}

interface FakeChart {
  options: unknown
  series: FakeSeries[]
  addSeries: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  remove: ReturnType<typeof vi.fn>
  timeScale: () => { fitContent: () => void }
}

const charts: FakeChart[] = []

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: { type: 'Candlestick' },
  LineSeries: { type: 'Line' },
  CrosshairMode: { Hidden: 2 },
  createChart: vi.fn((_el: HTMLElement, options: unknown) => {
    const chart: FakeChart = {
      options,
      series: [],
      addSeries: vi.fn((definition: { type: string }) => {
        const series: FakeSeries = {
          kind: definition.type,
          setData: vi.fn(),
          update: vi.fn(),
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

const T = 1_759_312_800_000
const bar = (i: number, c: number): Bar => ({ t_ms: T + i * 30_000, o: c, h: c + 5, l: c - 5, c })
const sixBars = [260, 262, 258, 270, 266, 280].map((c, i) => bar(i, c))

const tokens = (bg: string) => ({
  '--candle-up': '#10b981',
  '--candle-down': '#ef4444',
  '--sma-line': '#fbbf24',
  '--grid': '#1a2744',
  '--muted': '#9aa7bd',
  '--input-bg': bg,
})
const theme = (revision: number, bg = '#0a1426'): ThemeData => ({
  preset: 'blauw',
  revision,
  tokens: tokens(bg),
  font_family: 'Inter',
})

function setStore(patch: Partial<ExchangeState>) {
  act(() => exchangeStore.setState(patch))
}

const candles = (chart: FakeChart) => chart.series.find((s) => s.kind === 'Candlestick')!
const sma = (chart: FakeChart) => chart.series.find((s) => s.kind === 'Line')!
const seconds = (b: Bar) => ({ time: b.t_ms / 1000, open: b.o, high: b.h, low: b.l, close: b.c })

beforeEach(() => {
  charts.length = 0
  exchangeStore.setState(
    {
      ...exchangeStore.getInitialState(),
      bars: { 1: sixBars, 2: sixBars },
      snapshotGen: 1,
      theme: theme(1),
    },
    true,
  )
})

afterEach(cleanup)

describe('mount and live updates (AC27, AC12, AC35)', () => {
  it('sets each series once from the store on mount', () => {
    render(<DrinkChart drinkId={1} />)
    const [chart] = charts
    expect(candles(chart).setData).toHaveBeenCalledTimes(1)
    expect(sma(chart).setData).toHaveBeenCalledTimes(1)
  })

  it('passes the server bars through unchanged, times in seconds (AC12)', () => {
    render(<DrinkChart drinkId={1} />)
    expect(candles(charts[0]).setData).toHaveBeenCalledWith(sixBars.map(seconds))
  })

  it('draws the SMA of sma.ts over the same bars (AC35)', () => {
    render(<DrinkChart drinkId={1} />)
    expect(sma(charts[0]).setData).toHaveBeenCalledWith(
      smaSeries(sixBars).map((p) => ({ time: p.t_ms / 1000, value: p.value })),
    )
  })

  it('updates on a tick, never setData', () => {
    render(<DrinkChart drinkId={1} />)
    const [chart] = charts
    const replaced = [...sixBars.slice(0, 5), bar(5, 300)]
    setStore({ bars: { 1: replaced, 2: sixBars } })
    const appended = [...replaced, bar(6, 290)]
    setStore({ bars: { 1: appended, 2: sixBars } })

    expect(candles(chart).setData).toHaveBeenCalledTimes(1)
    expect(sma(chart).setData).toHaveBeenCalledTimes(1)
    expect(candles(chart).update.mock.calls).toEqual([
      [seconds(bar(5, 300))],
      [seconds(bar(6, 290))],
    ])
    const last = smaSeries(appended).at(-1)!
    expect(sma(chart).update).toHaveBeenLastCalledWith({
      time: last.t_ms / 1000,
      value: last.value,
    })
    expect(chart.remove).not.toHaveBeenCalled()
  })

  it('ignores a change to another drink and to prices alone (an order)', () => {
    render(<DrinkChart drinkId={1} />)
    setStore({ bars: { 1: sixBars, 2: [...sixBars, bar(6, 1)] } })
    setStore({ prices: { 1: { price_cents: 999, chart_price_cents: 999 } } })
    expect(candles(charts[0]).update).not.toHaveBeenCalled()
    expect(candles(charts[0]).setData).toHaveBeenCalledTimes(1)
  })

  it('sets data again only on a new snapshot', () => {
    render(<DrinkChart drinkId={1} />)
    const fresh = [bar(0, 100), bar(1, 110)]
    setStore({ bars: { 1: fresh }, snapshotGen: 2 })
    expect(candles(charts[0]).setData).toHaveBeenCalledTimes(2)
    expect(candles(charts[0]).setData).toHaveBeenLastCalledWith(fresh.map(seconds))
    expect(candles(charts[0]).update).not.toHaveBeenCalled()
  })
})

describe('theme (AC11)', () => {
  it('applies the tokens on a theme change, without a new chart', () => {
    render(<DrinkChart drinkId={1} />)
    const [chart] = charts
    setStore({ theme: theme(2, '#111111') })

    expect(charts).toHaveLength(1)
    expect(chart.remove).not.toHaveBeenCalled()
    expect(chart.applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({
        layout: expect.objectContaining({ background: { color: '#111111' }, textColor: '#9aa7bd' }),
      }),
    )
    expect(candles(chart).applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ upColor: '#10b981', downColor: '#ef4444' }),
    )
    expect(sma(chart).applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: '#fbbf24' }),
    )
  })
})

describe('lifecycle (AC28, AC29)', () => {
  it('removes the chart exactly once per mount under StrictMode', () => {
    const { unmount } = render(
      <StrictMode>
        <DrinkChart drinkId={1} />
      </StrictMode>,
    )
    unmount()
    for (const chart of charts) expect(chart.remove).toHaveBeenCalledTimes(1)
    // after unmount no store change reaches a removed chart
    setStore({ bars: { 1: [...sixBars, bar(6, 1)] } })
    for (const chart of charts) expect(candles(chart).update).not.toHaveBeenCalled()
  })

  it('keeps an unchanged drink chart across reorders and renames', () => {
    const List = ({ ids }: { ids: number[] }) => (
      <>
        {ids.map((id) => (
          <DrinkChart key={id} drinkId={id} />
        ))}
      </>
    )
    const { rerender } = render(<List ids={[1, 2]} />)
    expect(charts).toHaveLength(2)
    rerender(<List ids={[2, 1]} />)
    setStore({ drinks: [{ drink_id: 1, name: 'Nieuw' }] })
    expect(charts).toHaveLength(2)
    for (const chart of charts) expect(chart.remove).not.toHaveBeenCalled()
  })
})

describe('options', () => {
  it('ports v1 options: autosize, no scroll or scale, crosshair hidden, minutes on the axis', () => {
    render(<DrinkChart drinkId={1} />)
    expect(charts[0].options).toEqual(
      expect.objectContaining({
        autoSize: true,
        handleScroll: false,
        handleScale: false,
        crosshair: expect.objectContaining({ mode: 2 }),
        timeScale: expect.objectContaining({ timeVisible: true, secondsVisible: false }),
      }),
    )
  })
})

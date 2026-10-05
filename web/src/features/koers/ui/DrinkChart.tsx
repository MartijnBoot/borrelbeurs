/**
 * One drink's candle chart: a stable host, fed imperatively
 * (frontend-architecture.md, "The koers page"). React renders an empty `div`;
 * the chart lives in refs for the component's life, and a store subscription
 * drives it, so a tick causes no React render.
 *
 * - **Mount:** `setData` from the store's bars and their SMA.
 * - **Tick:** the drink's last bar and SMA point go to `update` (AC27). An
 *   order moves prices, not bars, so it leaves the chart alone.
 * - **Snapshot** (a new `snapshotGen`): `setData` again -- the only other time.
 * - **Theme:** `applyOptions` with the tokens; the chart is never recreated
 *   (AC11).
 * - **Unmount:** `remove` once and null the refs, so StrictMode's double
 *   cleanup is a no-op (AC28).
 *
 * The caller keys it by `drink_id`, so a reorder or rename keeps every chart
 * (AC29).
 */
import {
  CandlestickSeries,
  createChart,
  LineSeries,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import {
  exchangeStore,
  selectTheme,
  smaSeries,
  useExchange,
  type Bar,
  type DrinkId,
  type ExchangeState,
  type SmaPoint,
} from '../../exchange'
import { BASE_OPTIONS, candleColors, chartColors, SMA_OPTIONS, smaColors } from './chartOptions'

const time = (t_ms: number) => (t_ms / 1000) as UTCTimestamp

function candle(bar: Bar): CandlestickData {
  return { time: time(bar.t_ms), open: bar.o, high: bar.h, low: bar.l, close: bar.c }
}

function smaPoint(point: SmaPoint): LineData {
  return { time: time(point.t_ms), value: point.value }
}

interface Handles {
  chart: IChartApi
  candles: ISeriesApi<'Candlestick'>
  sma: ISeriesApi<'Line'>
}

export function DrinkChart({ drinkId }: { drinkId: DrinkId }) {
  const host = useRef<HTMLDivElement>(null)
  const handles = useRef<Handles | null>(null)
  const theme = useExchange(selectTheme)

  useEffect(() => {
    const element = host.current
    if (element === null) return
    const chart = createChart(element, BASE_OPTIONS)
    const candles = chart.addSeries(CandlestickSeries)
    const sma = chart.addSeries(LineSeries, SMA_OPTIONS)
    handles.current = { chart, candles, sma }

    const fill = (bars: readonly Bar[]) => {
      candles.setData(bars.map(candle))
      sma.setData(smaSeries(bars).map(smaPoint))
      chart.timeScale().fitContent()
    }

    let state: ExchangeState = exchangeStore.getState()
    fill(state.bars[drinkId] ?? [])

    const unsubscribe = exchangeStore.subscribe((next) => {
      const previous = state
      state = next
      const bars = next.bars[drinkId] ?? []
      if (next.snapshotGen !== previous.snapshotGen) {
        fill(bars)
        return
      }
      const last = bars.at(-1)
      if (last === undefined || bars === previous.bars[drinkId]) return
      candles.update(candle(last))
      const point = smaSeries(bars).at(-1)
      if (point !== undefined) sma.update(smaPoint(point))
    })

    return () => {
      unsubscribe()
      if (handles.current?.chart === chart) handles.current = null
      chart.remove()
    }
  }, [drinkId])

  useEffect(() => {
    const current = handles.current
    if (current === null || theme === null) return
    current.chart.applyOptions(chartColors(theme.tokens))
    current.candles.applyOptions(candleColors(theme.tokens))
    current.sma.applyOptions(smaColors(theme.tokens))
  }, [theme])

  return <div ref={host} style={{ width: '100%', height: '100%' }} />
}

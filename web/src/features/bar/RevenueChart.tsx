/**
 * Cumulative revenue for the live run (Phase 5 SD16): a stable host fed
 * imperatively, after `DrinkChart`. React renders an empty `div`; the chart
 * lives for the component's life and a store subscription drives it.
 *
 * - **Mount, and every snapshot** (a new `snapshotGen`): fetch the history
 *   and `setData(merge(history, live))`. A snapshot also clears the live
 *   points: the refetched history covers them.
 * - **Order** (`lastOrderTsMs` moved, no new snapshot): a live point at that
 *   second, valued at the store's revenue total, goes to `update` -- only
 *   ever `update` (AC22). When the point is older than the chart's last -- an
 *   order inside the open history bucket, whose end lies ahead -- it is
 *   placed at that last time instead: `update` replaces the point there, the
 *   library cannot update backwards (AC21), and the value is the newer total.
 * - **Theme:** `applyOptions` with the shared colours and `--accent` for the
 *   line (PD13); never a new chart (AC23).
 * - **Unmount:** `remove` once; a fetch that resolves later is ignored (AC22).
 *
 * At ≤640 px nothing is constructed and nothing fetched (SD17, AC24).
 * Revenue is the server's total, never computed here (AC17).
 */
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { BASE_OPTIONS, chartColors } from '../../lib/chartTheme'
import { exchangeStore, selectTheme, selectTotals, useExchange } from '../exchange'
import { fetchEarningsSeries } from './api/earningsSeries'
import { appendLive, livePoint, merge, toChartData, type RevenuePoint } from './model/revenueSeries'
import { useMediaQuery } from './useMediaQuery'

const NARROW = '(max-width: 640px)'

export function RevenueChart() {
  return useMediaQuery(NARROW) ? null : <RevenueChartHost />
}

interface Handles {
  chart: IChartApi
  line: ISeriesApi<'Line'>
}

function RevenueChartHost() {
  const host = useRef<HTMLDivElement>(null)
  const handles = useRef<Handles | null>(null)
  const theme = useExchange(selectTheme)

  useEffect(() => {
    const element = host.current
    if (element === null) return
    const chart = createChart(element, BASE_OPTIONS)
    const line = chart.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false })
    handles.current = { chart, line }

    let alive = true
    let request = 0
    let history: readonly RevenuePoint[] = []
    let live: readonly RevenuePoint[] = []
    let shownLast: number | null = null

    const show = () => {
      const data = toChartData(merge(history, live))
      line.setData(data)
      shownLast = data.at(-1)?.time ?? null
      chart.timeScale().fitContent()
    }

    const load = () => {
      const mine = ++request
      fetchEarningsSeries().then(
        (points) => {
          if (!alive || mine !== request) return
          history = points
          show()
        },
        () => {}, // the chart keeps what it has; a 401 already went to login
      )
    }

    let state = exchangeStore.getState()
    load()

    const unsubscribe = exchangeStore.subscribe((next) => {
      const previous = state
      state = next
      if (next.snapshotGen !== previous.snapshotGen) {
        live = []
        load()
        return
      }
      if (next.lastOrderTsMs === null || next.lastOrderTsMs === previous.lastOrderTsMs) return
      const point = livePoint(next.lastOrderTsMs, selectTotals(next).revenueCents)
      const before = live
      live = appendLive(live, point)
      if (live === before) return
      const [shown] = toChartData([point])
      const time = (
        shownLast === null ? shown.time : Math.max(shown.time, shownLast)
      ) as UTCTimestamp
      line.update({ ...shown, time })
      shownLast = time
    })

    return () => {
      alive = false
      unsubscribe()
      if (handles.current?.chart === chart) handles.current = null
      chart.remove()
    }
  }, [])

  useEffect(() => {
    const current = handles.current
    if (current === null || theme === null) return
    current.chart.applyOptions(chartColors(theme.tokens))
    current.line.applyOptions({ color: theme.tokens['--accent'] })
  }, [theme])

  return <div ref={host} style={{ width: '100%', height: '100%' }} />
}

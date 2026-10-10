/**
 * A run's cumulative revenue (Phase 7 SD9, SD10), after `bar/RevenueChart.tsx`:
 * a `lightweight-charts` line in the shared theme, its values in integer cents
 * (the axis formats them as euros). The 1 / 5 / 15 minute picker refetches
 * `GET /api/earnings/series?run_id=&bucket_s=` and the same chart is redrawn.
 * A run without sales shows "Geen verkopen" and constructs no chart.
 */
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { Select } from '../../components/ui/Select'
import { BASE_OPTIONS, chartColors } from '../../lib/chartTheme'
import { selectTheme, useExchange } from '../exchange'
import styles from './analytics.module.css'
import { type BucketSeconds, fetchSeries, type SeriesPoint } from './api/runDetail'

const BUCKETS = [
  { value: '60', label: '1 minuut' },
  { value: '300', label: '5 minuten' },
  { value: '900', label: '15 minuten' },
] as const

type Bucket = (typeof BUCKETS)[number]['value']

export interface SeriesChartProps {
  runId: number
}

export function SeriesChart({ runId }: SeriesChartProps) {
  const [bucket, setBucket] = useState<Bucket>('60')
  const [points, setPoints] = useState<SeriesPoint[] | undefined>(undefined)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let current = true
    fetchSeries(runId, Number(bucket) as BucketSeconds).then(
      (series) => {
        if (!current) return
        setPoints(series)
        setFailed(false)
      },
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [runId, bucket])

  return (
    <div>
      <Select label="Interval" value={bucket} options={BUCKETS} onChange={setBucket} />
      {failed && <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>}
      {!failed && points?.length === 0 && <p className={styles.muted}>Geen verkopen</p>}
      {!failed && points !== undefined && points.length > 0 && <ChartHost points={points} />}
    </div>
  )
}

interface Handles {
  chart: IChartApi
  line: ISeriesApi<'Line'>
}

function ChartHost({ points }: { points: readonly SeriesPoint[] }) {
  const host = useRef<HTMLDivElement>(null)
  const handles = useRef<Handles | null>(null)
  const theme = useExchange(selectTheme)

  useEffect(() => {
    const element = host.current
    if (element === null) return
    const chart = createChart(element, BASE_OPTIONS)
    const line = chart.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false })
    handles.current = { chart, line }
    return () => {
      handles.current = null
      chart.remove()
    }
  }, [])

  useEffect(() => {
    const current = handles.current
    if (current === null) return
    current.line.setData(
      points.map((p) => ({ time: (p.t_ms / 1000) as UTCTimestamp, value: p.cum_revenue_cents })),
    )
    current.chart.timeScale().fitContent()
  }, [points])

  useEffect(() => {
    const current = handles.current
    if (current === null || theme === null) return
    current.chart.applyOptions(chartColors(theme.tokens))
    current.line.applyOptions({ color: theme.tokens['--accent'] })
  }, [theme])

  return <div ref={host} style={{ width: '100%', height: 260 }} />
}

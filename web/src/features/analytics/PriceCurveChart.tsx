/**
 * One product's price in two runs (Phase 7 SD10, PD13; AC29): two
 * `lightweight-charts` lines on one minutes axis, after `SeriesChart`.
 *
 * The library's x axis is a time axis, so minutes since each run's start are
 * plotted as that many minutes of seconds from 0 (`minute * 60`) and the ticks
 * read "N min" -- no plugin. A bucket with a gap (`price_cents: null`) is a
 * whitespace point, so the line breaks there. The 1 / 5 / 15 minute picker
 * refetches; the same chart is redrawn. With no points in either run, "Geen
 * data voor dit drankje" and no chart.
 */
import {
  createChart,
  LineSeries,
  type ChartOptions,
  type DeepPartial,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
  type WhitespaceData,
  type LineData,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { Select } from '../../components/ui/Select'
import { BASE_OPTIONS, chartColors } from '../../lib/chartTheme'
import { selectTheme, useExchange } from '../exchange'
import styles from './analytics.module.css'
import { type CurvePoint, fetchPriceCurve, type PriceCurve } from './api/compare'
import type { BucketSeconds } from './api/runDetail'

const BUCKETS = [
  { value: '60', label: '1 minuut' },
  { value: '300', label: '5 minuten' },
  { value: '900', label: '15 minuten' },
] as const

type Bucket = (typeof BUCKETS)[number]['value']

const minutes = (time: Time) => `${Math.round(Number(time) / 60)} min`

const OPTIONS: DeepPartial<ChartOptions> = {
  ...BASE_OPTIONS,
  timeScale: { ...BASE_OPTIONS.timeScale, tickMarkFormatter: minutes },
  localization: { ...BASE_OPTIONS.localization, timeFormatter: minutes },
}

function toLine(points: readonly CurvePoint[]): (LineData | WhitespaceData)[] {
  return points.map((p) => {
    const time = (p.minute * 60) as UTCTimestamp
    return p.price_cents === null ? { time } : { time, value: p.price_cents }
  })
}

export interface PriceCurveChartProps {
  productId: number
  a: number
  b: number
}

export function PriceCurveChart({ productId, a, b }: PriceCurveChartProps) {
  const [bucket, setBucket] = useState<Bucket>('60')
  const [curve, setCurve] = useState<PriceCurve | undefined>(undefined)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let current = true
    fetchPriceCurve(productId, a, b, Number(bucket) as BucketSeconds).then(
      (data) => {
        if (!current) return
        setCurve(data)
        setFailed(false)
      },
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [productId, a, b, bucket])

  const empty = curve !== undefined && curve.a.length === 0 && curve.b.length === 0
  return (
    <div>
      <Select label="Interval" value={bucket} options={BUCKETS} onChange={setBucket} />
      {failed && <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>}
      {!failed && empty && <p className={styles.muted}>Geen data voor dit drankje</p>}
      {!failed && curve !== undefined && !empty && <CurveHost curve={curve} />}
    </div>
  )
}

interface Handles {
  chart: IChartApi
  a: ISeriesApi<'Line'>
  b: ISeriesApi<'Line'>
}

function CurveHost({ curve }: { curve: PriceCurve }) {
  const host = useRef<HTMLDivElement>(null)
  const handles = useRef<Handles | null>(null)
  const theme = useExchange(selectTheme)

  useEffect(() => {
    const element = host.current
    if (element === null) return
    const chart = createChart(element, OPTIONS)
    const series = { lineWidth: 2, priceLineVisible: false } as const
    handles.current = {
      chart,
      a: chart.addSeries(LineSeries, { ...series, title: 'A' }),
      b: chart.addSeries(LineSeries, { ...series, title: 'B' }),
    }
    return () => {
      handles.current = null
      chart.remove()
    }
  }, [])

  useEffect(() => {
    const current = handles.current
    if (current === null) return
    current.a.setData(toLine(curve.a))
    current.b.setData(toLine(curve.b))
    current.chart.timeScale().fitContent()
  }, [curve])

  useEffect(() => {
    const current = handles.current
    if (current === null || theme === null) return
    current.chart.applyOptions(chartColors(theme.tokens))
    current.a.applyOptions({ color: theme.tokens['--accent'] })
    current.b.applyOptions({ color: theme.tokens['--sma-line'] })
  }, [theme])

  return <div ref={host} style={{ width: '100%', height: 260 }} />
}

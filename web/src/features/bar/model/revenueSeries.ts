/**
 * The revenue chart's series, all pure (Phase 5 SD16).
 *
 * - **History** comes from `GET /api/earnings/series`: cumulative revenue at
 *   60 s bucket ends, ascending.
 * - **Live:** each in-sequence `order` message gives a point at its envelope
 *   `ts_ms` floored to the second, valued at the store's total after applying
 *   it. A point in the same second replaces the last one (AC21).
 * - **Merge:** history at or after the first live point's time is dropped.
 *
 * Values stay integer cents; the chart formats them (`formatEuro`).
 */
import type { UTCTimestamp } from 'lightweight-charts'

export interface RevenuePoint {
  readonly t_ms: number
  readonly cum_revenue_cents: number
}

export function livePoint(tsMs: number, totalCents: number): RevenuePoint {
  return { t_ms: tsMs - (tsMs % 1000), cum_revenue_cents: totalCents }
}

export function appendLive(
  points: readonly RevenuePoint[],
  point: RevenuePoint,
): readonly RevenuePoint[] {
  const last = points.at(-1)
  if (last === undefined || point.t_ms > last.t_ms) return [...points, point]
  if (point.t_ms === last.t_ms) return [...points.slice(0, -1), point]
  return points // older than the last point: the chart cannot take it
}

export function merge(
  history: readonly RevenuePoint[],
  live: readonly RevenuePoint[],
): RevenuePoint[] {
  const first = live[0]
  if (first === undefined) return [...history]
  return [...history.filter((p) => p.t_ms < first.t_ms), ...live]
}

/** `{time, value}` in seconds and cents, strictly ascending as the chart requires. */
export function toChartData(points: readonly RevenuePoint[]) {
  const data: { time: UTCTimestamp; value: number }[] = []
  for (const p of points) {
    const time = Math.floor(p.t_ms / 1000) as UTCTimestamp
    const last = data.at(-1)
    if (last !== undefined && time <= last.time) continue
    data.push({ time, value: p.cum_revenue_cents })
  }
  return data
}

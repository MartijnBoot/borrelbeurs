// The revenue series adapter (Phase 5 T13, SD16): live points, the merge,
// and strictly ascending chart times (AC21).
import { describe, expect, it } from 'vitest'
import { appendLive, livePoint, merge, toChartData, type RevenuePoint } from './revenueSeries'

describe('livePoint', () => {
  it('floors the order time to the second', () => {
    expect(livePoint(12_345_678, 900)).toEqual({ t_ms: 12_345_000, cum_revenue_cents: 900 })
  })
})

describe('appendLive', () => {
  it('two sales in one second give one point with the later value (AC21)', () => {
    const one = appendLive([], livePoint(10_100, 250))
    const two = appendLive(one, livePoint(10_900, 520))
    expect(two).toEqual([{ t_ms: 10_000, cum_revenue_cents: 520 }])
  })

  it('appends a later second and ignores an earlier one', () => {
    const points = appendLive([livePoint(10_000, 250)], livePoint(11_000, 500))
    expect(points).toHaveLength(2)
    expect(appendLive(points, livePoint(9_000, 1))).toBe(points)
  })
})

describe('merge', () => {
  const history: RevenuePoint[] = [
    { t_ms: 60_000, cum_revenue_cents: 100 },
    { t_ms: 120_000, cum_revenue_cents: 300 },
    { t_ms: 180_000, cum_revenue_cents: 600 },
  ]

  it('drops history at or after the first live point', () => {
    const live = [livePoint(120_000, 350), livePoint(125_000, 400)]
    expect(merge(history, live)).toEqual([history[0], ...live])
  })

  it('keeps all history with no live points', () => {
    expect(merge(history, [])).toEqual(history)
  })
})

describe('toChartData', () => {
  it('maps to seconds and cents', () => {
    expect(toChartData([{ t_ms: 60_000, cum_revenue_cents: 100 }])).toEqual([
      { time: 60, value: 100 },
    ])
  })

  it('is strictly ascending for random histories and live streams (AC21)', () => {
    let a = 12345
    const rand = () => (a = (a * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    for (let run = 0; run < 200; run++) {
      const history: RevenuePoint[] = []
      let t = 0
      for (let i = 0; i < rand() * 10; i++) {
        t += 60_000
        history.push({ t_ms: t, cum_revenue_cents: i })
      }
      let live: readonly RevenuePoint[] = []
      let ts = rand() * t
      for (let i = 0; i < rand() * 20; i++) {
        ts += rand() * 1500 - 200 // mostly forward, sometimes a little back
        live = appendLive(live, livePoint(Math.floor(ts), i))
      }
      const times = toChartData(merge(history, live)).map((p) => p.time)
      for (let i = 1; i < times.length; i++) expect(times[i]).toBeGreaterThan(times[i - 1])
    }
  })
})

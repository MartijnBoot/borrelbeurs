import { describe, expect, it } from 'vitest'
import { reconnectDelayMs } from './backoff'
import { SkewEstimator } from './skew'

describe('SkewEstimator (SD18, PD11)', () => {
  it('has no offset before any sample', () => {
    expect(new SkewEstimator().offsetMs()).toBeNull()
  })

  it('falls back to hello.ts_ms - received before the first pong', () => {
    const skew = new SkewEstimator()
    skew.fallback(10_500, 10_000)
    expect(skew.offsetMs()).toBe(500)
  })

  it('offset = server_ts - (sent + received) / 2', () => {
    const skew = new SkewEstimator()
    skew.fallback(99_999, 0)
    skew.sample(1_000, 1_100, 2_050) // rtt 100, midpoint 1050
    expect(skew.offsetMs()).toBe(1_000)
  })

  it('keeps the sample with the smallest round trip', () => {
    const skew = new SkewEstimator()
    skew.sample(0, 400, 1_000) // rtt 400 -> offset 800
    skew.sample(1_000, 1_020, 2_110) // rtt 20 -> offset 1100
    skew.sample(2_000, 2_300, 3_000) // rtt 300 -> offset 850
    expect(skew.offsetMs()).toBe(1_100)
  })

  it('forgets samples older than the last eight', () => {
    const skew = new SkewEstimator()
    skew.sample(0, 10, 5_005) // rtt 10, offset 5000: the best, then evicted
    for (let k = 1; k <= 8; k++) skew.sample(k * 1_000, k * 1_000 + 50, k * 1_000 + 25 + k)
    expect(skew.offsetMs()).toBe(1) // all rtt 50; the first of the eight wins ties
  })
})

describe('reconnectDelayMs (SD15, AC15)', () => {
  const curve = (n: number) => Math.min(500 * 1.7 ** n, 8_000)

  it.each([0, 1, 2, 3, 6, 10])('attempt %i sits within ±30%% of the capped curve', (n) => {
    expect(reconnectDelayMs(n, () => 0)).toBeCloseTo(curve(n) * 0.7)
    expect(reconnectDelayMs(n, () => 0.5)).toBeCloseTo(curve(n))
    expect(reconnectDelayMs(n, () => 1)).toBeCloseTo(curve(n) * 1.3)
  })

  it('starts at 500 ms and caps at 8 s', () => {
    expect(reconnectDelayMs(0, () => 0.5)).toBe(500)
    expect(reconnectDelayMs(20, () => 0.5)).toBe(8_000)
  })
})

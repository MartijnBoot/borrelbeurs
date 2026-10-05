import { describe, expect, it } from 'vitest'
import { smaSeries } from './sma'

const bar = (t_ms: number, c: number) => ({ t_ms, o: c, h: c, l: c, c })

describe('smaSeries (SD11, AC35)', () => {
  it('has no point before five bars', () => {
    expect(smaSeries([bar(0, 100), bar(1, 200), bar(2, 300), bar(3, 400)], 5)).toEqual([])
  })

  it('averages the last five closes at every bar from the fifth', () => {
    const bars = [100, 200, 300, 400, 500, 600, 1000].map((c, i) => bar(i * 30_000, c))
    expect(smaSeries(bars, 5)).toEqual([
      { t_ms: 120_000, value: 300 }, // (100+200+300+400+500)/5
      { t_ms: 150_000, value: 400 }, // (200+300+400+500+600)/5
      { t_ms: 180_000, value: 560 }, // (300+400+500+600+1000)/5
    ])
  })

  it('follows a tick replacing the last bar close', () => {
    const bars = [100, 200, 300, 400, 500].map((c, i) => bar(i, c))
    const replaced = [...bars.slice(0, 4), bar(4, 1000)]
    expect(smaSeries(replaced, 5)).toEqual([{ t_ms: 4, value: 400 }]) // (100+200+300+400+1000)/5
  })

  it('reads closes, not opens or highs', () => {
    const bars = [1, 2, 3, 4, 5].map((c, i) => ({ t_ms: i, o: 0, h: 999, l: 0, c }))
    expect(smaSeries(bars, 5)).toEqual([{ t_ms: 4, value: 3 }])
  })
})

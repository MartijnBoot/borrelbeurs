/**
 * The SMA line: the mean of the last `window` bar closes, at every bar from
 * the `window`-th on (SD11; v1's `SMA_WINDOW = 5`, `koers.html:385`). Computed
 * over the bars the server sent -- never over a synthesised candle.
 */
import type { Bar } from './schemas'

export const SMA_WINDOW = 5

export interface SmaPoint {
  t_ms: number
  value: number
}

export function smaSeries(bars: readonly Bar[], window: number = SMA_WINDOW): SmaPoint[] {
  const points: SmaPoint[] = []
  let sum = 0
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c
    if (i >= window) sum -= bars[i - window].c
    if (i >= window - 1) points.push({ t_ms: bars[i].t_ms, value: sum / window })
  }
  return points
}

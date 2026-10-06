/**
 * The candle chart's options, ported from v1's `createCandleChart`
 * (`koers.html:396-425`) with every hardcoded colour replaced by a theme
 * token, so a theme change is one `applyOptions` call per object (AC11).
 * The shared base options and colours live in `lib/chartTheme.ts` (Phase 5
 * PD14); the candle and SMA pieces stay here.
 *
 * Prices stay integer cents in the chart -- the bars go in exactly as the
 * server sent them (AC12) -- and the axis shows them through the one euro
 * formatter.
 */
export { BASE_OPTIONS, chartColors, type Tokens } from '../../../lib/chartTheme'
import type { Tokens } from '../../../lib/chartTheme'

export function candleColors(tokens: Tokens) {
  const up = tokens['--candle-up']
  const down = tokens['--candle-down']
  return {
    upColor: up,
    downColor: down,
    borderUpColor: up,
    borderDownColor: down,
    wickUpColor: up,
    wickDownColor: down,
  }
}

export function smaColors(tokens: Tokens) {
  return { color: tokens['--sma-line'] }
}

export const SMA_OPTIONS = {
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
} as const

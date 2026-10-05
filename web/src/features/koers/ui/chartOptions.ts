/**
 * The candle chart's options, ported from v1's `createCandleChart`
 * (`koers.html:396-425`) with every hardcoded colour replaced by a theme
 * token, so a theme change is one `applyOptions` call per object (AC11).
 *
 * Prices stay integer cents in the chart -- the bars go in exactly as the
 * server sent them (AC12) -- and the axis shows them through the one euro
 * formatter.
 */
import { CrosshairMode, type ChartOptions, type DeepPartial } from 'lightweight-charts'
import { formatEuro } from '../../../lib/format'

export type Tokens = Readonly<Record<string, string>>

/** Options fixed for the chart's life; colours come from `chartColors`. */
export const BASE_OPTIONS: DeepPartial<ChartOptions> = {
  autoSize: true,
  layout: { fontSize: 12 },
  timeScale: { timeVisible: true, secondsVisible: false },
  crosshair: { mode: CrosshairMode.Hidden },
  handleScroll: false,
  handleScale: false,
  localization: { priceFormatter: formatEuro },
}

export function chartColors(tokens: Tokens): DeepPartial<ChartOptions> {
  const grid = tokens['--grid']
  return {
    layout: { background: { color: tokens['--input-bg'] }, textColor: tokens['--muted'] },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    timeScale: { borderColor: grid },
    rightPriceScale: { borderColor: grid },
  }
}

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

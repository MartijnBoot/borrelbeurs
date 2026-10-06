/**
 * The chart theme every lightweight-charts chart shares (Phase 5 PD14): the
 * fixed options and the token-driven colours. Moved from koers so the bar's
 * revenue chart uses the same theme without a sibling-feature import.
 *
 * Values stay integer cents in every chart; the axis shows them through the
 * one euro formatter.
 */
import { CrosshairMode, type ChartOptions, type DeepPartial } from 'lightweight-charts'
import { formatEuro } from './format'

export type Tokens = Readonly<Record<string, string>>

/** Options fixed for a chart's life; colours come from `chartColors`. */
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

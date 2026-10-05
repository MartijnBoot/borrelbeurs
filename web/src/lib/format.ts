/**
 * The one euro formatter, and the tile's delta text (SD22).
 *
 * Prices arrive as integer cents; the division here is for display only and
 * nothing computed from it goes back to the server.
 */

const EUR = new Intl.NumberFormat('nl-NL', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const PERCENT = new Intl.NumberFormat('nl-NL', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

/** `250` → `"€ 2,50"` (Intl's no-break space after the symbol). */
export function formatEuro(cents: number): string {
  return EUR.format(cents / 100)
}

/** A percentage, not a fraction: `12` → `"12,0%"`. */
export function formatPercent(pct: number): string {
  return `${PERCENT.format(pct)}%`
}

/** Ported from v1's `deltaStr` (`koers.html:646-652`), in SD22's formats. */
export function deltaText(prevCents: number, curCents: number): string {
  const d = curCents - prevCents
  if (d === 0) return '—'
  const sign = d > 0 ? '▲' : '▼'
  const pct = prevCents !== 0 ? (d / prevCents) * 100 : 0
  return `${sign} ${formatEuro(d)} (${formatPercent(pct)})`
}

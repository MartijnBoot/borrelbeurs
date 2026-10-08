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

const EURO_TEXT = /^(\d+)(?:[.,](\d{1,2}))?$/

/**
 * A euro amount typed by a person, as integer cents (Phase 6 SD5): `""` is `null`;
 * "2,50" and "2.50" are 250; "2" is 200. More than two decimals, a second
 * separator, a sign or anything else is `'invalid'` -- never rounded. Exact: the
 * digits are read as text, never through `parseFloat(x) * 100`.
 */
export function parseEuroCents(text: string): FieldValue {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const match = EURO_TEXT.exec(trimmed)
  if (match === null) return 'invalid'
  const [, euros, decimals = ''] = match
  return Number(euros) * 100 + Number(decimals.padEnd(2, '0'))
}

/** Integer cents as the text a `MoneyField` shows: `250` → `"2,50"`. */
export function centsText(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const abs = Math.abs(cents)
  return `${sign}${Math.trunc(abs / 100)},${String(abs % 100).padStart(2, '0')}`
}

/** What a form field reports: a value, `null` for empty (never 0), or `'invalid'`. */
export type FieldValue = number | null | 'invalid'

const NUMBER_TEXT = /^-?\d+(?:[.,]\d+)?$/

/** A number typed by a person: a decimal comma or point; `""` is `null`; else `'invalid'`. */
export function parseNumber(text: string): FieldValue {
  const trimmed = text.trim()
  if (trimmed === '') return null
  if (!NUMBER_TEXT.test(trimmed)) return 'invalid'
  return Number(trimmed.replace(',', '.'))
}

/** A number as a `NumberField` shows it, with a decimal comma. */
export function numberText(value: number | null): string {
  return value === null ? '' : String(value).replace('.', ',')
}

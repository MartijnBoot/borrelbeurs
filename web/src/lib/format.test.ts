import { describe, expect, it } from 'vitest'
import { deltaText, formatEuro, formatPercent } from './format'

// Intl's nl-NL currency format separates the symbol with a no-break space.
const NBSP = ' '

describe('formatEuro', () => {
  it.each([
    [0, `€${NBSP}0,00`],
    [5, `€${NBSP}0,05`],
    [250, `€${NBSP}2,50`],
    [1000, `€${NBSP}10,00`],
    [123456, `€${NBSP}1.234,56`],
    [-30, `€${NBSP}-0,30`],
  ])('formats %i cents as %s', (cents, text) => {
    expect(formatEuro(cents)).toBe(text)
  })
})

describe('formatPercent', () => {
  it.each([
    [0, '0,0%'],
    [12, '12,0%'],
    [-12.345, '-12,3%'],
  ])('formats %d as %s', (pct, text) => {
    expect(formatPercent(pct)).toBe(text)
  })
})

describe('deltaText', () => {
  it('is a dash when the price is unchanged', () => {
    expect(deltaText(250, 250)).toBe('—')
  })

  it('shows a rise with ▲, the amount and the percentage', () => {
    expect(deltaText(250, 280)).toBe(`▲ €${NBSP}0,30 (12,0%)`)
  })

  it('shows a fall with ▼ and signed values, as v1 did', () => {
    expect(deltaText(250, 220)).toBe(`▼ €${NBSP}-0,30 (-12,0%)`)
  })

  it('shows 0,0% when the previous price was zero', () => {
    expect(deltaText(0, 5)).toBe(`▲ €${NBSP}0,05 (0,0%)`)
  })
})

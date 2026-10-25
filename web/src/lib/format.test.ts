import { describe, expect, it } from 'vitest'
import { deltaParts, formatBalance, formatEuro, formatPercent, parseEuroCents } from './format'

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

// B-06 PD11: a balance below zero gets a leading U+2212 minus; formatEuro is unchanged.
describe('formatBalance', () => {
  it.each([
    [-210, `\u2212€${NBSP}2,10`],
    [0, `€${NBSP}0,00`],
    [750, `€${NBSP}7,50`],
  ])('formats %i cents as %s', (cents, text) => {
    expect(formatBalance(cents)).toBe(text)
  })

  it('leaves formatEuro as the koers deltas need it', () => {
    expect(formatEuro(-30)).toBe(`€${NBSP}-0,30`)
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

// B-02 PD7: the direction is an icon now, so the text carries no symbol.
describe('deltaParts', () => {
  it('is a dash with no direction when the price is unchanged', () => {
    expect(deltaParts(250, 250)).toEqual({ direction: null, text: '—' })
  })

  it('gives a rise, the amount and the percentage', () => {
    expect(deltaParts(250, 280)).toEqual({ direction: 'rise', text: `€${NBSP}0,30 (12,0%)` })
  })

  it('gives a fall with signed values, as v1 did', () => {
    expect(deltaParts(250, 220)).toEqual({ direction: 'fall', text: `€${NBSP}-0,30 (-12,0%)` })
  })

  it('shows 0,0% when the previous price was zero', () => {
    expect(deltaParts(0, 5)).toEqual({ direction: 'rise', text: `€${NBSP}0,05 (0,0%)` })
  })
})

describe('parseEuroCents', () => {
  it.each([
    ['', null],
    ['   ', null],
    ['2,50', 250],
    ['2.50', 250],
    ['2', 200],
    ['2,5', 250],
    ['0,05', 5],
    [' 12,00 ', 1200],
    ['0', 0],
    ['1234,56', 123456],
  ])('%j gives %j', (text, cents) => {
    expect(parseEuroCents(text)).toBe(cents)
  })

  it.each(['2,505', '1.2.3', '2,5.0', '-2', '+2', 'abc', '2,', ',5', '€2', '1e2', '2 50'])(
    '%j is invalid',
    (text) => {
      expect(parseEuroCents(text)).toBe('invalid')
    },
  )

  it('is exact where float arithmetic is not', () => {
    // parseFloat('0.29') * 100 === 28.999999999999996
    expect(parseEuroCents('0,29')).toBe(29)
    expect(parseEuroCents('1,13')).toBe(113)
  })
})

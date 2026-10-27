// B-07 T9 (PD8): the grid model. The texts are the spec's own, the same strings
// `tests/unit/test_price_grid.py` pins on the server.
import { describe, expect, it } from 'vitest'
import { boundMoves, gridMessage, neighbours, offGridHint, onGrid, stepCents } from './grid'

const drink = (name: string, slot: number, low: number, high: number, active = true) => ({
  name,
  slot,
  active,
  p_min_cents: low,
  p_max_cents: high,
})

describe('grid', () => {
  it('reads the step in whole cents', () => {
    expect(stepCents(0.1)).toBe(10)
    expect(stepCents(0.25)).toBe(25)
    expect(stepCents(0.05)).toBe(5)
    expect(stepCents(5)).toBe(500)
  })

  it('refuses 124 on 0,10 and 160 on 0,25 with their two neighbours', () => {
    expect(onGrid(124, 10)).toBe(false)
    expect(gridMessage(124, 10)).toBe(
      'Moet een veelvoud van de Prijsstap (0,10) zijn: 1,20 of 1,30.',
    )
    expect(onGrid(160, 25)).toBe(false)
    expect(gridMessage(160, 25)).toBe(
      'Moet een veelvoud van de Prijsstap (0,25) zijn: 1,50 of 1,75.',
    )
  })

  it('accepts 120, 0, 150 and 175 on their steps', () => {
    expect([
      onGrid(120, 10),
      onGrid(0, 10),
      onGrid(150, 25),
      onGrid(175, 25),
      onGrid(0, 25),
    ]).toEqual([true, true, true, true, true])
  })

  it('names the neighbours and the stored-value hint', () => {
    expect(neighbours(124, 10)).toEqual([120, 130])
    expect(neighbours(3, 10)).toEqual([0, 10])
    expect(offGridHint(124, 10)).toBe('Niet op de Prijsstap: kies 1,20 of 1,30.')
  })

  it('lists the moves for a new step: active drinks, slot order, Minimum first', () => {
    const drinks = [
      drink('Fris', 2, 105, 255),
      drink('Bier', 0, 160, 310),
      drink('Wijn', 1, 150, 500),
      drink('Oud', 3, 105, 255, false),
    ]
    expect(boundMoves(drinks, 25)).toEqual([
      { name: 'Bier', field: 'p_min_cents', from: 160, to: 175 },
      { name: 'Bier', field: 'p_max_cents', from: 310, to: 300 },
      { name: 'Fris', field: 'p_min_cents', from: 105, to: 125 },
      { name: 'Fris', field: 'p_max_cents', from: 255, to: 250 },
    ])
    expect(boundMoves(drinks.slice(2, 3), 25)).toEqual([])
  })
})

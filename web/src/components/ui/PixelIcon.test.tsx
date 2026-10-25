// @vitest-environment jsdom
// The pixel icons (B-02 SD1, SD3, SD10; PD1, PD2; B-04 SD11; B-05 SD25): 23 grids of `#` and `.`, each drawn
// as one inline SVG path that covers exactly the grid's `#` cells.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PixelIcon, type PixelIconName } from './PixelIcon'
import grids from './pixelIcons.json'

afterEach(cleanup)

const LARGE = [
  'broom',
  'gear',
  'palette',
  'picture',
  'cup',
  'padlock',
  'chart',
  'key',
  'newspaper',
  'burst',
  'bolt',
  'hourglass',
  'beer',
  'banknote',
  'warning',
  'arrowUp',
  'floppy',
  'wallet',
]
const SMALL = ['stop', 'rise', 'fall', 'chevronDown']
const ALL: Record<string, readonly string[]> = grids
const ICONS = Object.keys(grids).filter((name) => name !== 'favicon') as PixelIconName[]

/** The cells `d` paints, as `x,y`; only the `M x y h w v1 h-w z` runs PD2 writes. */
function painted(d: string): Set<string> {
  const cells = new Set<string>()
  const runs = [...d.matchAll(/M(\d+) (\d+)h(\d+)v1h-(\d+)z/g)]
  expect(runs.map((run) => run[0]).join('')).toBe(d)
  for (const [, x, y, w, back] of runs) {
    expect(back).toBe(w)
    for (let i = 0; i < Number(w); i++) {
      const cell = `${Number(x) + i},${y}`
      expect(cells.has(cell), `${cell} painted twice`).toBe(false)
      cells.add(cell)
    }
  }
  return cells
}

function onCells(grid: readonly string[]): Set<string> {
  const cells = new Set<string>()
  grid.forEach((row, y) => [...row].forEach((c, x) => c === '#' && cells.add(`${x},${y}`)))
  return cells
}

describe('the grids (AC1)', () => {
  it('are exactly the 23 of SD10, B-04 SD11 and B-05 SD25: 18 of 16×16, 4 of 8×8 and the 16×16 favicon', () => {
    expect(Object.keys(grids).sort()).toEqual([...LARGE, ...SMALL, 'favicon'].sort())
    for (const name of [...LARGE, 'favicon']) expect(ALL[name], name).toHaveLength(16)
    for (const name of SMALL) expect(ALL[name], name).toHaveLength(8)
  })

  it.each(Object.keys(grids))('%s is square, `#` and `.` only, with at least one `#`', (name) => {
    const grid = ALL[name]
    for (const row of grid) {
      expect(row).toHaveLength(grid.length)
      expect(row).toMatch(/^[#.]+$/)
    }
    expect(grid.join('')).toContain('#')
  })
})

describe('PixelIcon (AC2, AC4, AC8)', () => {
  it.each(ICONS)('%s draws exactly its own grid’s `#` cells', (name) => {
    const { container } = render(<PixelIcon name={name} />)
    const svg = container.querySelector('svg')!
    const n = ALL[name].length
    expect(svg.getAttribute('viewBox')).toBe(`0 0 ${n} ${n}`)
    const paths = svg.querySelectorAll('path')
    expect(paths).toHaveLength(1)
    expect(painted(paths[0].getAttribute('d')!)).toEqual(onCells(ALL[name]))
  })

  it('is one colour, crisp and 1em tall', () => {
    const { container } = render(<PixelIcon name="gear" />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('fill')).toBe('currentColor')
    expect(svg.getAttribute('shape-rendering')).toBe('crispEdges')
    expect(svg.getAttribute('height')).toBe('1em')
    expect(svg.getAttribute('width')).toBe('1em')
  })

  it('is hidden from assistive tech unless it is given a label', () => {
    const { container } = render(<PixelIcon name="gear" />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.hasAttribute('role')).toBe(false)
    expect(svg.textContent).toBe('')
  })

  it('is an image with the given name when it is given a label (SD11)', () => {
    render(<PixelIcon name="rise" label="stijgt" />)
    const img = screen.getByRole('img', { name: 'stijgt' })
    expect(img.hasAttribute('aria-hidden')).toBe(false)
    expect(img.textContent).toBe('')
  })

  it.each(ICONS)('%s requests no file: no <title>, <image>, <use> or href', (name) => {
    const { container } = render(<PixelIcon name={name} label="x" />)
    const svg = container.querySelector('svg')!
    expect(svg.querySelectorAll('title, image, use')).toHaveLength(0)
    for (const el of [svg, ...svg.querySelectorAll('*')]) {
      for (const attr of el.getAttributeNames()) expect(attr).not.toMatch(/href$/)
    }
  })

  it('passes a class through', () => {
    const { container } = render(<PixelIcon name="key" className="extra" />)
    expect(container.querySelector('svg')!.classList.contains('extra')).toBe(true)
  })
})

// @vitest-environment jsdom
// The QR code (B-05 SD14, AC9): one rect per dark module, drawn without markup.
import { cleanup, render, screen } from '@testing-library/react'
import { encode } from 'uqr'
import { afterEach, describe, expect, it } from 'vitest'
import { QrCode } from './QrCode'

afterEach(cleanup)

const TOKEN = 'q2h5bq0V3cXhT7zZp1kY9w'

describe('QrCode', () => {
  it('draws exactly the dark modules of the encoded token', () => {
    render(<QrCode token={TOKEN} />)
    const svg = screen.getByRole('img', { name: 'QR-code' })
    const modules = encode(TOKEN, { ecc: 'M', border: 2 }).data
    const dark = modules.flat().filter(Boolean).length

    const rects = Array.from(svg.querySelectorAll('rect'))
    expect(rects).toHaveLength(dark)
    expect(svg.getAttribute('viewBox')).toBe(`0 0 ${modules.length} ${modules.length}`)
    expect(svg.getAttribute('shape-rendering')).toBe('crispEdges')
    expect(new Set(rects.map((rect) => rect.getAttribute('fill')))).toEqual(new Set(['#000']))
    for (const rect of rects) {
      const [x, y] = [Number(rect.getAttribute('x')), Number(rect.getAttribute('y'))]
      expect(modules[y][x]).toBe(true)
    }
  })

  it('another token draws another code', () => {
    const { container, rerender } = render(<QrCode token={TOKEN} />)
    const first = container.innerHTML
    rerender(<QrCode token="another-token-entirely" />)
    expect(container.innerHTML).not.toBe(first)
  })
})

// @vitest-environment jsdom
// Two runs side by side (Phase 7 T22: AC11 (UI), AC28 (UI), AC30 (UI), AC33):
// "—" for a product absent from one side, no request until both runs are chosen,
// and the product select driving the price curve.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CompareView } from './CompareView'

const curves: { productId: number; a: number; b: number }[] = []
vi.mock('./PriceCurveChart', () => ({
  PriceCurveChart: (props: { productId: number; a: number; b: number }) => {
    curves.push(props)
    return <p>curve {props.productId}</p>
  },
}))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const side = (qty: number, revenue: number) => ({
  qty,
  revenue_cents: revenue,
  bar_price_total_cents: qty * 250,
})

const ROWS = [
  { product_key: 'product:1', product_id: 1, name: 'Pils', a: side(2, 500), b: side(3, 900) },
  { product_key: 'product:2', product_id: 2, name: 'Wijn', a: side(1, 300), b: null },
  { product_key: 'name:fris', product_id: null, name: 'Fris', a: null, b: side(4, 600) },
]

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  curves.length = 0
  fetchMock = vi.fn(async () => json(200, ROWS))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

describe('CompareView', () => {
  it.each([
    [null, null],
    [2, null],
    [null, 3],
  ])('with a=%s and b=%s shows "Kies twee borrels" and sends nothing', async (a, b) => {
    render(<CompareView a={a} b={b} />)
    await settle()

    expect(screen.getByText('Kies twee borrels')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows both sides per product, "—" where a product is absent', async () => {
    render(<CompareView a={2} b={3} />)
    await settle()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/analytics/compare?a=2&b=3')
    const pils = within(screen.getByRole('row', { name: /^Pils/ }))
    expect(pils.getByText('€ 5,00')).toBeTruthy()
    expect(pils.getByText('€ 9,00')).toBeTruthy()
    const wijn = within(screen.getByRole('row', { name: /^Wijn/ }))
    expect(wijn.getAllByText('—')).toHaveLength(2) // B's qty and revenue
    const fris = within(screen.getByRole('row', { name: /^Fris/ }))
    expect(fris.getAllByText('—')).toHaveLength(2) // A's qty and revenue
    expect(fris.getByText('€ 6,00')).toBeTruthy()
  })

  it('the product select offers the products that have an id, and drives the curve', async () => {
    render(<CompareView a={2} b={3} />)
    await settle()

    const select = screen.getByLabelText('Drankje') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['Pils', 'Wijn'])
    expect(curves.at(-1)).toEqual({ productId: 1, a: 2, b: 3 })

    fireEvent.change(select, { target: { value: '2' } })
    expect(curves.at(-1)).toEqual({ productId: 2, a: 2, b: 3 })
  })

  it('two runs without sales show "Geen verkopen" and no curve', async () => {
    fetchMock.mockImplementation(async () => json(200, []))
    render(<CompareView a={2} b={3} />)
    await settle()

    expect(screen.getByText('Geen verkopen')).toBeTruthy()
    expect(curves).toHaveLength(0)
  })

  it('a failed fetch shows "Verbindingsfout"', async () => {
    fetchMock.mockImplementation(async () =>
      json(500, { error: { code: 'internal_error', message: 'x' } }),
    )
    render(<CompareView a={2} b={3} />)
    await settle()

    expect(screen.getByText(/Verbindingsfout/)).toBeTruthy()
  })
})

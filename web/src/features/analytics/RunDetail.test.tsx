// @vitest-environment jsdom
// A run's detail (Phase 7 T20: AC27 (UI), AC30 (UI), AC33): the per-product table
// with removed drinks marked, the totals, the empty state and a fetch error.
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RunDetail } from './RunDetail'

vi.mock('./SeriesChart', () => ({ SeriesChart: () => null }))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const product = (name: string, qty: number, revenue: number, removed = false) => ({
  product_key: `name:${name.toLowerCase()}`,
  product_id: null,
  name,
  qty,
  revenue_cents: revenue,
  bar_price_total_cents: qty * 250,
  avg_price_cents: Math.round(revenue / qty),
  removed,
})

const detail = (perProduct: unknown[], totals: { qty: number; revenue: number }) => ({
  run_id: 2,
  name: 'Vrijmibo',
  status: 'ended',
  t0_ms: 0,
  ended_at_ms: 3_600_000,
  duration_ms: 3_600_000,
  qty: totals.qty,
  revenue_cents: totals.revenue,
  bar_price_total_cents: totals.qty * 250,
  per_product: perProduct,
})

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

describe('RunDetail', () => {
  it('shows each product, marks a removed one, and the totals', async () => {
    fetchMock.mockResolvedValue(
      json(
        200,
        detail([product('Bier', 3, 740), product('Wijn', 1, 310, true)], { qty: 4, revenue: 1050 }),
      ),
    )
    render(<RunDetail runId={2} />)
    await settle()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/analytics/runs/2')
    const bier = within(screen.getByRole('row', { name: /^Bier/ }))
    expect(bier.getByText('3')).toBeTruthy()
    expect(bier.getByText('€ 7,40')).toBeTruthy()
    expect(bier.getByText('€ 7,50')).toBeTruthy() // 3 × the 250 bar price
    expect(bier.getByText('€ 2,47')).toBeTruthy()
    expect(bier.queryByText('verwijderd')).toBeNull()
    expect(within(screen.getByRole('row', { name: /^Wijn/ })).getByText('verwijderd')).toBeTruthy()
    const total = within(screen.getByRole('row', { name: /^Totaal/ }))
    expect(total.getByText('4')).toBeTruthy()
    expect(total.getByText('€ 10,50')).toBeTruthy()
  })

  it('a run without sales shows "Geen verkopen"', async () => {
    fetchMock.mockResolvedValue(json(200, detail([], { qty: 0, revenue: 0 })))
    render(<RunDetail runId={2} />)
    await settle()

    expect(screen.getByText('Geen verkopen')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('a failed fetch shows "Verbindingsfout"', async () => {
    fetchMock.mockResolvedValue(json(500, { error: { code: 'internal_error', message: 'x' } }))
    render(<RunDetail runId={2} />)
    await settle()

    expect(screen.getByText(/Verbindingsfout/)).toBeTruthy()
  })

  it('fetches again for another run', async () => {
    fetchMock.mockImplementation(async () => json(200, detail([], { qty: 0, revenue: 0 })))
    const { rerender } = render(<RunDetail runId={2} />)
    await settle()
    rerender(<RunDetail runId={5} />)
    await settle()

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/api/analytics/runs/2',
      '/api/analytics/runs/5',
    ])
  })
})

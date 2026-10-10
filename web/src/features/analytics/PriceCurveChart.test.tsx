// @vitest-environment jsdom
// The price-curve overlay (Phase 7 T22: AC29 (UI), AC30 (UI); PD13) against a
// mocked lightweight-charts: two line series on a minutes axis, a `null` bucket
// as a whitespace point so the line breaks, the 1 / 5 / 15 picker, and the
// empty state.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PriceCurveChart } from './PriceCurveChart'

interface FakeChart {
  options: { timeScale?: { tickMarkFormatter?: (time: number) => string } }
  series: { setData: ReturnType<typeof vi.fn> }[]
  remove: ReturnType<typeof vi.fn>
}

const charts: FakeChart[] = []

vi.mock('lightweight-charts', () => ({
  LineSeries: { type: 'Line' },
  CrosshairMode: { Hidden: 2 },
  createChart: vi.fn((_el: HTMLElement, options: FakeChart['options']) => {
    const chart: FakeChart = { options, series: [], remove: vi.fn() }
    charts.push(chart)
    return {
      addSeries: () => {
        const series = { setData: vi.fn(), applyOptions: vi.fn() }
        chart.series.push(series)
        return series
      },
      applyOptions: vi.fn(),
      remove: chart.remove,
      timeScale: () => ({ fitContent: () => {} }),
    }
  }),
}))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  charts.length = 0
  fetchMock = vi.fn(async () =>
    json(200, {
      a: [
        { minute: 0, price_cents: 250 },
        { minute: 1, price_cents: null },
        { minute: 2, price_cents: 270 },
      ],
      b: [{ minute: 0, price_cents: 300 }],
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

describe('PriceCurveChart', () => {
  it('draws A and B on one chart, a null bucket as a whitespace point', async () => {
    render(<PriceCurveChart productId={7} a={2} b={3} />)
    await settle()

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/analytics/price-curve?product_id=7&a=2&b=3&bucket_s=60',
    )
    expect(charts).toHaveLength(1)
    const [a, b] = charts[0].series
    expect(a.setData).toHaveBeenLastCalledWith([
      { time: 0, value: 250 },
      { time: 60 },
      { time: 120, value: 270 },
    ])
    expect(b.setData).toHaveBeenLastCalledWith([{ time: 0, value: 300 }])
  })

  it('labels the axis in minutes', async () => {
    render(<PriceCurveChart productId={7} a={2} b={3} />)
    await settle()

    expect(charts[0].options.timeScale?.tickMarkFormatter?.(300)).toBe('5 min')
  })

  it('the picker refetches with 900 on the same chart', async () => {
    render(<PriceCurveChart productId={7} a={2} b={3} />)
    await settle()

    fireEvent.change(screen.getByLabelText('Interval'), { target: { value: '900' } })
    await settle()

    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      '/api/analytics/price-curve?product_id=7&a=2&b=3&bucket_s=900',
    )
    expect(charts).toHaveLength(1)
  })

  it('a product with no points in either run shows "Geen data voor dit drankje"', async () => {
    fetchMock.mockImplementation(async () => json(200, { a: [], b: [] }))
    render(<PriceCurveChart productId={7} a={2} b={3} />)
    await settle()

    expect(screen.getByText('Geen data voor dit drankje')).toBeTruthy()
    expect(charts).toHaveLength(0)
  })

  it('a failed fetch shows "Verbindingsfout"', async () => {
    fetchMock.mockImplementation(async () =>
      json(500, { error: { code: 'internal_error', message: 'x' } }),
    )
    render(<PriceCurveChart productId={7} a={2} b={3} />)
    await settle()

    expect(screen.getByText(/Verbindingsfout/)).toBeTruthy()
  })
})

// @vitest-environment jsdom
// A run's earnings series (Phase 7 T20: AC30 (UI), AC33; SD9) against a mocked
// lightweight-charts: the 1 / 5 / 15 minute picker refetches, an empty run
// constructs no chart, and a fetch error shows "Verbindingsfout".
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SeriesChart } from './SeriesChart'

interface FakeChart {
  setData: ReturnType<typeof vi.fn>
  remove: ReturnType<typeof vi.fn>
}

const charts: FakeChart[] = []

vi.mock('lightweight-charts', () => ({
  LineSeries: { type: 'Line' },
  CrosshairMode: { Hidden: 2 },
  TickMarkType: { Year: 0, Month: 1, DayOfMonth: 2, Time: 3, TimeWithSeconds: 4 },
  createChart: vi.fn(() => {
    const chart: FakeChart = { setData: vi.fn(), remove: vi.fn() }
    charts.push(chart)
    return {
      addSeries: () => ({ setData: chart.setData, applyOptions: vi.fn() }),
      applyOptions: vi.fn(),
      remove: chart.remove,
      timeScale: () => ({ fitContent: () => {} }),
    }
  }),
}))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const POINTS = [
  { t_ms: 60_000, cum_revenue_cents: 250 },
  { t_ms: 120_000, cum_revenue_cents: 770 },
]

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  charts.length = 0
  fetchMock = vi.fn(async () => json(200, POINTS))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

const paths = () => (fetchMock.mock.calls as [string][]).map(([path]) => path)

describe('SeriesChart', () => {
  it('fetches the run at 1 minute and draws the points in cents at seconds', async () => {
    render(<SeriesChart runId={4} />)
    await settle()

    expect(paths()).toEqual(['/api/earnings/series?run_id=4&bucket_s=60'])
    expect(charts).toHaveLength(1)
    expect(charts[0].setData).toHaveBeenLastCalledWith([
      { time: 60, value: 250 },
      { time: 120, value: 770 },
    ])
  })

  it('the picker refetches with 300 and redraws the same chart', async () => {
    render(<SeriesChart runId={4} />)
    await settle()

    fireEvent.change(screen.getByLabelText('Interval'), { target: { value: '300' } })
    await settle()

    expect(paths().at(-1)).toBe('/api/earnings/series?run_id=4&bucket_s=300')
    expect(charts).toHaveLength(1)
    expect(charts[0].setData).toHaveBeenCalledTimes(2)
  })

  it('an empty run shows "Geen verkopen" and constructs no chart', async () => {
    fetchMock.mockImplementation(async () => json(200, []))
    render(<SeriesChart runId={4} />)
    await settle()

    expect(screen.getByText('Geen verkopen')).toBeTruthy()
    expect(charts).toHaveLength(0)
  })

  it('a fetch error shows "Verbindingsfout"', async () => {
    fetchMock.mockImplementation(async () =>
      json(500, { error: { code: 'internal_error', message: 'x' } }),
    )
    render(<SeriesChart runId={4} />)
    await settle()

    expect(screen.getByText(/Verbindingsfout/)).toBeTruthy()
    expect(charts).toHaveLength(0)
  })

  it('removes its chart on unmount', async () => {
    const { unmount } = render(<SeriesChart runId={4} />)
    await settle()
    unmount()

    expect(charts[0].remove).toHaveBeenCalledTimes(1)
  })
})

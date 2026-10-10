// @vitest-environment jsdom
// `/analytics` (Phase 7 T19: AC8 (UI), AC32, AC33; SD10): the run list in euros,
// "loopt" for a live run, the empty state, picking a run for detail and two for
// compare, and a delete guarded by the typed name.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsPage } from './AnalyticsPage'

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const HOUR = 3_600_000
const T0 = Date.UTC(2025, 9, 3, 18, 0) // Friday 3 October 2025, 20:00 in Amsterdam

const ended = {
  run_id: 2,
  name: 'Vrijmibo',
  status: 'ended',
  t0_ms: T0,
  ended_at_ms: T0 + 2 * HOUR + 30 * 60_000,
  duration_ms: 2 * HOUR + 30 * 60_000,
  qty: 41,
  revenue_cents: 10_250,
  bar_price_total_cents: 9_840,
}
const live = {
  ...ended,
  run_id: 3,
  name: 'Nu',
  status: 'live',
  ended_at_ms: null,
  duration_ms: null,
  qty: 3,
  revenue_cents: 780,
  bar_price_total_cents: 750,
}

let fetchMock: ReturnType<typeof vi.fn>
let runs: unknown[]

beforeEach(() => {
  runs = [live, ended]
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'GET' && path === '/api/analytics/runs') return json(200, runs)
    if (method === 'DELETE' && path === '/api/runs/2') {
      runs = [live]
      return new Response(null, { status: 204 })
    }
    return json(404, { error: { code: 'not_stubbed', message: path } })
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

const row = (name: string) => screen.getByRole('row', { name: new RegExp(`^${name}\\b`) })

describe('AnalyticsPage: run list', () => {
  it('shows each run in euros, with "loopt" for the live run', async () => {
    render(<AnalyticsPage />)
    await settle()

    const vrijmibo = within(row('Vrijmibo'))
    expect(vrijmibo.getByText('Afgelopen')).toBeTruthy()
    expect(vrijmibo.getByText('€ 102,50')).toBeTruthy()
    expect(vrijmibo.getByText('€ 98,40')).toBeTruthy()
    expect(vrijmibo.getByText('41')).toBeTruthy()
    expect(vrijmibo.getByText('2:30')).toBeTruthy()
    const nu = within(row('Nu'))
    expect(nu.getByText('loopt')).toBeTruthy()
    expect(nu.getByText('€ 7,80')).toBeTruthy()
  })

  it('with no runs shows "Nog geen borrels"', async () => {
    runs = []
    render(<AnalyticsPage />)
    await settle()

    expect(screen.getByText('Nog geen borrels')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('a failed list shows "Verbindingsfout"', async () => {
    fetchMock.mockImplementationOnce(async () => json(500, { error: { code: 'x', message: 'x' } }))
    render(<AnalyticsPage />)
    await settle()

    expect(screen.getByText(/Verbindingsfout/)).toBeTruthy()
  })

  it('picks a run for detail and two for compare', async () => {
    render(<AnalyticsPage />)
    await settle()

    expect(screen.getByText('Kies een borrel voor details.')).toBeTruthy()
    fireEvent.click(within(row('Vrijmibo')).getByRole('button', { name: 'Details' }))
    expect(screen.getByRole('region', { name: 'Details van Vrijmibo' })).toBeTruthy()

    const a = within(row('Vrijmibo')).getByRole('radio', { name: 'A' }) as HTMLInputElement
    const b = within(row('Nu')).getByRole('radio', { name: 'B' }) as HTMLInputElement
    expect(screen.getByText('Kies twee borrels')).toBeTruthy()
    fireEvent.click(a)
    expect(screen.getByText('Kies twee borrels')).toBeTruthy()
    fireEvent.click(b)
    expect(a.checked && b.checked).toBe(true)
    expect(screen.queryByText('Kies twee borrels')).toBeNull()
  })

  it('the live run cannot be deleted', async () => {
    render(<AnalyticsPage />)
    await settle()

    expect(within(row('Nu')).queryByRole('button', { name: 'Verwijderen' })).toBeNull()
  })
})

describe('AnalyticsPage: delete', () => {
  it('is guarded by the typed name, then deletes and refreshes', async () => {
    render(<AnalyticsPage />)
    await settle()
    fireEvent.click(within(row('Vrijmibo')).getByRole('button', { name: 'Details' }))

    fireEvent.click(within(row('Vrijmibo')).getByRole('button', { name: 'Verwijderen' }))
    const confirm = screen.getByRole('button', {
      name: 'Verwijderen bevestigen',
    }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("Typ de naam 'Vrijmibo' om te bevestigen"), {
      target: { value: 'Vrijmibo' },
    })
    fireEvent.click(confirm)
    await settle()

    const deletes = (fetchMock.mock.calls as [string, RequestInit | undefined][]).filter(
      ([, init]) => init?.method === 'DELETE',
    )
    expect(deletes).toEqual([
      ['/api/runs/2', expect.objectContaining({ body: '{"confirm_name":"Vrijmibo"}' })],
    ])
    expect(screen.queryByRole('row', { name: /^Vrijmibo\b/ })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Details van Vrijmibo' })).toBeNull()
  })

  it('cancel sends nothing', async () => {
    render(<AnalyticsPage />)
    await settle()

    fireEvent.click(within(row('Vrijmibo')).getByRole('button', { name: 'Verwijderen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await settle()

    expect(
      (fetchMock.mock.calls as [string, RequestInit | undefined][]).some(
        ([, init]) => init?.method === 'DELETE',
      ),
    ).toBe(false)
  })

  it('a refused delete shows its Dutch text', async () => {
    fetchMock.mockImplementation(async (_path: string, init?: RequestInit) =>
      init?.method === 'DELETE'
        ? json(409, { error: { code: 'run_live', message: 'live' } })
        : json(200, runs),
    )
    render(<AnalyticsPage />)
    await settle()

    fireEvent.click(within(row('Vrijmibo')).getByRole('button', { name: 'Verwijderen' }))
    fireEvent.change(screen.getByLabelText("Typ de naam 'Vrijmibo' om te bevestigen"), {
      target: { value: 'Vrijmibo' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verwijderen bevestigen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Sluit de borrel eerst af.')
  })
})

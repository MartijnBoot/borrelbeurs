// @vitest-environment jsdom
// The export panel (Phase 7 T21: AC7, AC17, AC20 (UI), AC33; SD12) with fake
// timers: a poll every 2 s while an export is queued or running and none after
// it is done, the download link, "Opnieuw", and the export_busy text.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ExportPanel } from './ExportPanel'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const exportRow = (id: number, status: string, extra: Record<string, unknown> = {}) => ({
  export_id: id,
  run_id: 4,
  kind: 'manual',
  status,
  requested_by: 'Bestuur',
  sha256: null,
  bytes: status === 'done' ? 52_000 : null,
  line_count: null,
  total_cents: null,
  error: null,
  created_at_ms: Date.UTC(2025, 9, 3, 18, 0),
  started_at_ms: null,
  finished_at_ms: null,
  ...extra,
})

let fetchMock: ReturnType<typeof vi.fn>
let listed: unknown[]
let polled: () => unknown
let posted: () => Response

beforeEach(() => {
  vi.useFakeTimers()
  listed = []
  polled = () => exportRow(1, 'queued')
  posted = () => json(202, exportRow(9, 'queued'))
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'GET' && path === '/api/runs/4/exports') return json(200, listed)
    if (method === 'GET' && path.startsWith('/api/exports/')) return json(200, polled())
    if (method === 'POST' && path === '/api/runs/4/exports') return posted()
    return json(404, { error: { code: 'not_stubbed', message: path } })
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const polls = () =>
  (fetchMock.mock.calls as [string][]).filter(([path]) => path.startsWith('/api/exports/')).length

describe('ExportPanel', () => {
  it('polls every 2 s while an export is queued, and stops once it is done', async () => {
    listed = [exportRow(1, 'queued')]
    render(<ExportPanel runId={4} />)
    await settle()
    expect(screen.getByText('In de wachtrij')).toBeTruthy()

    await wait(1_999)
    expect(polls()).toBe(0)
    await wait(1)
    expect(polls()).toBe(1)
    polled = () => exportRow(1, 'running')
    await wait(2_000)
    expect(polls()).toBe(2)
    expect(screen.getByText('Bezig')).toBeTruthy()

    polled = () => exportRow(1, 'done')
    listed = [exportRow(1, 'done')]
    await wait(2_000)
    expect(polls()).toBe(3)
    await wait(10_000)
    expect(polls()).toBe(3)
  })

  it('a done export is a download link to its file', async () => {
    listed = [exportRow(7, 'done')]
    render(<ExportPanel runId={4} />)
    await settle()

    const link = screen.getByRole('link', { name: 'Download' })
    expect(link.getAttribute('href')).toBe('/api/exports/7/file')
    expect(link.hasAttribute('download')).toBe(true)
    expect(screen.getByText('51 kB')).toBeTruthy()
    await wait(10_000)
    expect(polls()).toBe(0)
  })

  it('reloads the list once an export finishes, so a pruned one leaves it (AC24)', async () => {
    listed = [
      exportRow(4, 'running'),
      exportRow(3, 'done'),
      exportRow(2, 'done'),
      exportRow(1, 'done'),
    ]
    render(<ExportPanel runId={4} />)
    await settle()
    expect(screen.getAllByRole('link', { name: 'Download' })).toHaveLength(3)

    // The fourth manual export is done; the server pruned the oldest (export 1).
    listed = [exportRow(4, 'done'), exportRow(3, 'done'), exportRow(2, 'done')]
    polled = () => exportRow(4, 'done')
    await wait(2_000)

    const links = screen.getAllByRole('link', { name: 'Download' })
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/api/exports/4/file',
      '/api/exports/3/file',
      '/api/exports/2/file',
    ])
  })

  it('"Exporteer (xlsx)" requests an export and shows it queued', async () => {
    render(<ExportPanel runId={4} />)
    await settle()
    expect(screen.getByText('Nog geen exports')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Exporteer (xlsx)' }))
    await settle()

    const posts = (fetchMock.mock.calls as [string, RequestInit | undefined][]).filter(
      ([, init]) => init?.method === 'POST',
    )
    expect(posts.map(([path]) => path)).toEqual(['/api/runs/4/exports'])
    expect(screen.getByText('In de wachtrij')).toBeTruthy()
  })

  it('a failed export shows its error, and "Opnieuw" requests again', async () => {
    listed = [exportRow(3, 'failed', { kind: 'final', error: 'onderbroken' })]
    render(<ExportPanel runId={4} />)
    await settle()

    const row = within(screen.getByRole('row', { name: /Eindexport/ }))
    expect(row.getByText('Onderbroken')).toBeTruthy()
    fireEvent.click(row.getByRole('button', { name: 'Opnieuw' }))
    await settle()

    expect(
      (fetchMock.mock.calls as [string, RequestInit | undefined][]).filter(
        ([, init]) => init?.method === 'POST',
      ),
    ).toHaveLength(1)
    expect(screen.getByText('In de wachtrij')).toBeTruthy()
  })

  it('a 409 export_busy shows its Dutch text', async () => {
    posted = () => json(409, { error: { code: 'export_busy', message: 'busy' } })
    render(<ExportPanel runId={4} />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Exporteer (xlsx)' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe(
      'Er loopt al een export. Probeer het zo opnieuw.',
    )
  })

  it('stops polling on unmount', async () => {
    listed = [exportRow(1, 'queued')]
    const { unmount } = render(<ExportPanel runId={4} />)
    await settle()
    unmount()

    await wait(10_000)
    expect(polls()).toBe(0)
  })
})

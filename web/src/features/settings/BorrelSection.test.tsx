// @vitest-environment jsdom
// The Borrel section (Phase 6 T24: SD4; AC24, AC25 (UI), AC39; PD2): the current
// run, "Nieuwe borrel" when there is none, and "Live zetten" behind ConfirmDialog.
// Phase 7 T18 (AC2, AC9, AC32; SD2, SD4; PD16): "Borrel afsluiten" behind a typed
// name, and "Kopieer drankjes uit" from GET /api/analytics/runs.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BorrelSection } from './BorrelSection'

const RUN_LIST = '/api/analytics/runs'

let fetchMock: ReturnType<typeof vi.fn>
let queue: (() => Response)[]
let runList: () => Response

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const noRun = () => json(404, { error: { code: 'no_current_run', message: 'none' } })
const draft = { run_id: 7, name: 'Vrijmibo', status: 'draft' }
const live = { ...draft, status: 'live' }

const listed = (run_id: number, name: string, status: string) => ({
  run_id,
  name,
  status,
  t0_ms: null,
  ended_at_ms: null,
  duration_ms: null,
  qty: 0,
  revenue_cents: 0,
  bar_price_total_cents: 0,
})

/**
 * Answer the run list with `runList`, and every other request from the queue, in
 * order. Past the queue's end a request gets `undefined`, as a bare `vi.fn()`
 * gives: the section's own refetch after a write then fails and keeps its run.
 */
function serve(...responses: (() => Response)[]) {
  queue = responses
  fetchMock.mockImplementation((path: string) =>
    Promise.resolve(path === RUN_LIST ? runList() : queue.shift()?.()),
  )
}

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  runList = () => json(200, [])
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
}

/** Every request but the run list's: `[path, method, body]`. */
function calls(): [string, string | undefined, string | undefined][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([path]) => path !== RUN_LIST)
    .map(([path, init]) => [
      path,
      init?.method,
      typeof init?.body === 'string' ? init.body : undefined,
    ])
}

describe('BorrelSection', () => {
  it('with no current run shows "Geen borrel" and the name form', async () => {
    serve(noRun)
    render(<BorrelSection />)
    await settle()

    expect(screen.getByText('Geen borrel')).toBeTruthy()
    expect(screen.getByLabelText('Naam')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nieuwe borrel' })).toBeTruthy()
  })

  it('submitting posts {name} and shows the new draft', async () => {
    serve(noRun, () => json(201, draft))
    render(<BorrelSection />)
    await settle()

    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Vrijmibo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()[1]).toEqual(['/api/runs', 'POST', '{"name":"Vrijmibo"}'])
    expect(screen.getByText('Vrijmibo')).toBeTruthy()
    expect(screen.getByText('Concept')).toBeTruthy()
  })

  it('a 409 draft_exists opens that draft', async () => {
    serve(
      noRun,
      () => json(409, { error: { code: 'draft_exists', message: 'exists', run_id: 7 } }),
      () => json(200, draft),
    )
    render(<BorrelSection />)
    await settle()

    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Anders' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()[2]).toEqual(['/api/runs/current', 'GET', undefined])
    expect(screen.getByText('Vrijmibo')).toBeTruthy()
  })

  it('an empty name sends nothing', async () => {
    serve(noRun)
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()).toHaveLength(1)
  })

  it('a live run shows its name and status, with no go-live', async () => {
    serve(() => json(200, live))
    render(<BorrelSection />)
    await settle()

    expect(screen.getByText('Live')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Live zetten' })).toBeNull()
  })

  it('"Live zetten" asks first: Cancel sends nothing, Confirm posts go-live', async () => {
    serve(
      () => json(200, draft),
      () => json(200, live),
    )
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    expect(screen.getByRole('dialog', { name: "'Vrijmibo' live zetten?" })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(calls()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(calls()[1]).toEqual(['/api/runs/7/go-live', 'POST', undefined])
    expect(screen.getByText('Live')).toBeTruthy()
  })

  it('shows a refused go-live in Dutch', async () => {
    serve(
      () => json(200, draft),
      () => json(409, { error: { code: 'run_not_ready', message: 'no drinks' } }),
    )
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Voeg eerst een drankje toe.')
  })
})

describe('BorrelSection: close (Phase 7 T18)', () => {
  it('a draft has no close button', async () => {
    serve(() => json(200, draft))
    render(<BorrelSection />)
    await settle()

    expect(screen.queryByRole('button', { name: 'Borrel afsluiten' })).toBeNull()
  })

  it('posts the close only once the typed name matches, then shows the new-borrel form', async () => {
    serve(
      () => json(200, live),
      () => json(200, { ...live, status: 'ended' }),
      noRun, // the refetch after the close
    )
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Borrel afsluiten' }))
    const confirm = screen.getByRole('button', { name: 'Afsluiten' }) as HTMLButtonElement
    const input = screen.getByLabelText("Typ de naam 'Vrijmibo' om te bevestigen")
    expect(confirm.disabled).toBe(true)
    fireEvent.change(input, { target: { value: 'vrijmibo' } })
    fireEvent.click(confirm)
    expect(calls()).toHaveLength(1)

    fireEvent.change(input, { target: { value: ' Vrijmibo ' } })
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await settle()

    expect(calls()[1]).toEqual(['/api/runs/7/close', 'POST', '{"confirm_name":"Vrijmibo"}'])
    expect(screen.getByText('Geen borrel')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nieuwe borrel' })).toBeTruthy()
  })

  it.each([
    [422, 'name_mismatch', 'Naam komt niet overeen.'],
    [409, 'run_not_live', 'Deze borrel is niet live.'],
  ])('a %i %s shows "%s"', async (status, code, text) => {
    serve(
      () => json(200, live),
      () => json(status, { error: { code, message: 'refused' } }),
    )
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Borrel afsluiten' }))
    fireEvent.change(screen.getByLabelText("Typ de naam 'Vrijmibo' om te bevestigen"), {
      target: { value: 'Vrijmibo' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Afsluiten' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe(text)
    expect(screen.getByText('Live')).toBeTruthy()
  })
})

describe('BorrelSection: copy from a past run (Phase 7 T18)', () => {
  it('offers the empty option plus the past runs, drafts left out', async () => {
    runList = () =>
      json(200, [
        listed(9, 'Vrijdag', 'ended'),
        listed(8, 'Nu', 'live'),
        listed(5, 'Plan', 'draft'),
      ])
    serve(noRun)
    render(<BorrelSection />)
    await settle()

    const select = screen.getByLabelText('Kopieer drankjes uit') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['—', 'Vrijdag', 'Nu'])
    expect(select.value).toBe('')
  })

  it('a chosen run reaches the POST body as copy_from_run_id', async () => {
    runList = () => json(200, [listed(9, 'Vrijdag', 'ended')])
    serve(noRun, () => json(201, draft))
    render(<BorrelSection />)
    await settle()

    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Vrijmibo' } })
    fireEvent.change(screen.getByLabelText('Kopieer drankjes uit'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()[1]).toEqual(['/api/runs', 'POST', '{"name":"Vrijmibo","copy_from_run_id":9}'])
  })

  it('a failed run-list fetch leaves the form usable with only the empty option', async () => {
    runList = () => json(500, { error: { code: 'internal_error', message: 'boom' } })
    serve(noRun, () => json(201, draft))
    render(<BorrelSection />)
    await settle()

    const select = screen.getByLabelText('Kopieer drankjes uit') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['—'])
    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Vrijmibo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()[1]).toEqual(['/api/runs', 'POST', '{"name":"Vrijmibo"}'])
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

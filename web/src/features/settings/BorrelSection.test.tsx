// @vitest-environment jsdom
// The Borrel section (Phase 6 T24: SD4; AC24, AC25 (UI), AC39; PD2): the current
// run, "Nieuwe borrel" when there is none, and "Live zetten" behind ConfirmDialog.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BorrelSection } from './BorrelSection'

let fetchMock: ReturnType<typeof vi.fn>

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const noRun = () => json(404, { error: { code: 'no_current_run', message: 'none' } })
const draft = { run_id: 7, name: 'Vrijmibo', status: 'draft' }

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

function calls(): [string, string | undefined, string | undefined][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][]).map(([path, init]) => [
    path,
    init?.method,
    typeof init?.body === 'string' ? init.body : undefined,
  ])
}

describe('BorrelSection', () => {
  it('with no current run shows "Geen borrel" and the name form', async () => {
    fetchMock.mockResolvedValueOnce(noRun())
    render(<BorrelSection />)
    await settle()

    expect(screen.getByText('Geen borrel')).toBeTruthy()
    expect(screen.getByLabelText('Naam')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Nieuwe borrel' })).toBeTruthy()
  })

  it('submitting posts {name} and shows the new draft', async () => {
    fetchMock.mockResolvedValueOnce(noRun()).mockResolvedValueOnce(json(201, draft))
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
    fetchMock
      .mockResolvedValueOnce(noRun())
      .mockResolvedValueOnce(
        json(409, { error: { code: 'draft_exists', message: 'exists', run_id: 7 } }),
      )
      .mockResolvedValueOnce(json(200, draft))
    render(<BorrelSection />)
    await settle()

    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Anders' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(calls()[2]).toEqual(['/api/runs/current', 'GET', undefined])
    expect(screen.getByText('Vrijmibo')).toBeTruthy()
  })

  it('an empty name sends nothing', async () => {
    fetchMock.mockResolvedValueOnce(noRun())
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe borrel' }))
    await settle()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('a live run shows its name and status, with no go-live', async () => {
    fetchMock.mockResolvedValueOnce(json(200, { ...draft, status: 'live' }))
    render(<BorrelSection />)
    await settle()

    expect(screen.getByText('Live')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Live zetten' })).toBeNull()
  })

  it('"Live zetten" asks first: Cancel sends nothing, Confirm posts go-live', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, draft))
      .mockResolvedValueOnce(json(200, { ...draft, status: 'live' }))
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    expect(screen.getByRole('dialog', { name: "'Vrijmibo' live zetten?" })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(fetchMock).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(calls()[1]).toEqual(['/api/runs/7/go-live', 'POST', undefined])
    expect(screen.getByText('Live')).toBeTruthy()
  })

  it('shows a refused go-live in Dutch', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, draft))
      .mockResolvedValueOnce(json(409, { error: { code: 'run_not_ready', message: 'no drinks' } }))
    render(<BorrelSection />)
    await settle()

    fireEvent.click(screen.getByRole('button', { name: 'Live zetten' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Voeg eerst een drankje toe.')
  })
})

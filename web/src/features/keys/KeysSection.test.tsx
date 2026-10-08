// @vitest-environment jsdom
// 🔑 Toegangssleutels (Phase 6 T32: SD30; AC36, AC38, AC39): the list, a new key
// shown exactly once, and revocation behind a dialog.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KeysSection } from './KeysSection'

const KEYS = [
  {
    key_id: 1,
    label: 'Bestuur',
    role: 'admin',
    created_at: '2026-10-01T18:00:00Z',
    last_used_at: '2026-10-08T19:30:00Z',
    revoked: false,
  },
  {
    key_id: 2,
    label: 'Tap 1',
    role: 'bar',
    created_at: '2026-10-02T18:00:00Z',
    last_used_at: null,
    revoked: true,
  },
]

const SECRET = 'bb_3_c2VjcmV0LXNlY3JldC1zZWNyZXQ'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>
let revokeAnswer: () => Response

beforeEach(() => {
  revokeAnswer = () => new Response(null, { status: 204 })
  fetchMock = vi.fn((_path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'GET') return Promise.resolve(json(200, KEYS))
    if (method === 'POST') return Promise.resolve(json(201, { key_id: 3, key: SECRET }))
    return Promise.resolve(revokeAnswer())
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
  await act(async () => {})
}

const writes = () =>
  (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([path, init]) => [path, init?.method, init?.body])

async function open() {
  render(<KeysSection />)
  await settle()
}

async function create() {
  fireEvent.change(screen.getByLabelText('Rol'), { target: { value: 'bar' } })
  fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Tap 2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Nieuwe sleutel' }))
  await settle()
}

describe('KeysSection', () => {
  it('lists every key with its status', async () => {
    await open()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Bestuur')).toBeTruthy()
    expect(within(rows[0]).getByText('Actief')).toBeTruthy()
    expect(within(rows[1]).getByText('Ingetrokken')).toBeTruthy()
  })

  it('a new key posts {role, label} and is shown once (AC36)', async () => {
    await open()
    await create()

    expect(writes()[0]).toEqual(['/api/keys', 'POST', '{"role":"bar","label":"Tap 2"}'])
    expect(screen.getByText(SECRET)).toBeTruthy()
    expect(screen.getByText('Wordt maar één keer getoond')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    await settle()
    expect(screen.queryByText(SECRET)).toBeNull()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('"Kopieer" copies the key to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await open()
    await create()

    fireEvent.click(screen.getByRole('button', { name: 'Kopieer' }))
    await settle()

    expect(writeText).toHaveBeenCalledWith(SECRET)
  })

  it('revoke asks first: Cancel sends nothing, Confirm sends DELETE (AC39)', async () => {
    await open()
    const bestuur = screen.getAllByRole('row')[1]
    fireEvent.click(within(bestuur).getByRole('button', { name: 'Intrekken' }))
    expect(screen.getByRole('dialog', { name: "'Bestuur' intrekken?" })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(writes()).toEqual([])

    fireEvent.click(within(bestuur).getByRole('button', { name: 'Intrekken' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()
    expect(writes()).toEqual([['/api/keys/1', 'DELETE', undefined]])
  })

  it('a revoked key offers no revoke', async () => {
    await open()
    const tap = screen.getAllByRole('row')[2]
    expect(within(tap).queryByRole('button', { name: 'Intrekken' })).toBeNull()
  })

  it('the last admin key refusal shows in Dutch (AC38)', async () => {
    revokeAnswer = () => json(409, { error: { code: 'last_admin_key', message: 'last' } })
    await open()
    fireEvent.click(
      within(screen.getAllByRole('row')[1]).getByRole('button', { name: 'Intrekken' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe(
      'Dit is de laatste beheerderssleutel; die kan niet worden ingetrokken.',
    )
  })
})

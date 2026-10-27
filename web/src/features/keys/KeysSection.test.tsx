// @vitest-environment jsdom
// Toegangssleutels (Phase 6 T32: SD30; AC36, AC38, AC39): the list, a new key
// shown exactly once, and revocation behind a dialog. B-08 T5 (SD8, SD9; AC15,
// AC16, D-50): the grouped key in a larger monospaced <code>, and "Kopieer"
// that selects the key instead of throwing when the clipboard is missing.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KeysSection } from './KeysSection'
import styles from './KeysSection.module.css'

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
  {
    key_id: 4,
    label: 'Kassa 1',
    role: 'kassa',
    created_at: '2026-10-25T18:00:00Z',
    last_used_at: null,
    revoked: false,
  },
]

const SECRET = 'K7M-4QX-9PR'
const HINT = 'Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem zelf.'

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
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('Bestuur')).toBeTruthy()
    expect(within(rows[0]).getByText('Actief')).toBeTruthy()
    expect(within(rows[1]).getByText('Ingetrokken')).toBeTruthy()
  })

  it('lists a kassa key as "Kassa" and creates one with role kassa (B-05 AC40)', async () => {
    await open()
    expect(within(screen.getAllByRole('row')[3]).getByText('Kassa')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Rol'), { target: { value: 'kassa' } })
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Kassa 2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe sleutel' }))
    await settle()

    expect(writes()[0]).toEqual(['/api/keys', 'POST', '{"role":"kassa","label":"Kassa 2"}'])
  })

  it('a new key posts {role, label} and is shown once (AC36)', async () => {
    await open()
    await create()

    expect(writes()[0]).toEqual(['/api/keys', 'POST', '{"role":"bar","label":"Tap 2"}'])
    const shown = screen.getByText(SECRET)
    expect(shown.tagName).toBe('CODE')
    expect(shown.classList.contains(styles.key)).toBe(true)
    expect(screen.getAllByText(SECRET)).toHaveLength(1)
    expect(screen.getByText('Wordt maar één keer getoond')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    await settle()
    expect(screen.queryByText(SECRET)).toBeNull()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('"Kopieer" copies the grouped key to the clipboard, with no hint (AC16)', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await open()
    await create()

    fireEvent.click(screen.getByRole('button', { name: 'Kopieer' }))
    await settle()

    expect(writeText).toHaveBeenCalledWith(SECRET)
    expect(screen.queryByText(HINT)).toBeNull()
  })

  it.each([
    [
      'writeText rejects',
      () => ({ clipboard: { writeText: vi.fn().mockRejectedValue(new Error('no')) } }),
    ],
    ['navigator.clipboard is missing (D-50)', () => ({})],
  ])('when %s, "Kopieer" selects the key and shows the hint (AC16)', async (_, nav) => {
    // A throw here would be an unhandled rejection, which fails the vitest run.
    vi.stubGlobal('navigator', nav())
    await open()
    await create()

    fireEvent.click(screen.getByRole('button', { name: 'Kopieer' }))
    await settle()

    expect(screen.getByRole('status').textContent).toBe(HINT)
    expect(window.getSelection()?.toString()).toBe(SECRET)
    expect(screen.getByText(SECRET)).toBeTruthy()
  })

  it('"Sluiten" after a failed copy clears the hint for the next key', async () => {
    vi.stubGlobal('navigator', {})
    await open()
    await create()
    fireEvent.click(screen.getByRole('button', { name: 'Kopieer' }))
    await settle()
    expect(screen.getByText(HINT)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    await settle()
    await create()

    expect(screen.getByText(SECRET)).toBeTruthy()
    expect(screen.queryByText(HINT)).toBeNull()
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

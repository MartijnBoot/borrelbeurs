// @vitest-environment jsdom
// The preset picker (SD10, AC3's admin action, AC8's client half).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ThemeData } from '../exchange'
import { ThemeSection } from './ThemeSection'

const LABELS = ['Oud Geld', 'Blauw', 'Groen', 'Paars', 'Rood']

const held: ThemeData = {
  preset: 'paars',
  revision: 3,
  tokens: {},
  font_family: 'Inter, system-ui, sans-serif',
}

let fetchMock: ReturnType<typeof vi.fn>

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  exchangeStore.setState({ ...exchangeStore.getInitialState(), theme: held }, true)
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<ThemeSection />)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const marked = () =>
  screen
    .getAllByRole('button')
    .filter((b) => b.getAttribute('aria-pressed') === 'true')
    .map((b) => b.textContent)

async function choose(label: string) {
  fireEvent.click(screen.getByRole('button', { name: label }))
  await act(async () => {})
}

describe('ThemeSection', () => {
  it('shows the five presets, the current one marked', () => {
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(LABELS)
    expect(marked()).toEqual(['Paars'])
  })

  it('selecting a preset sends PUT /api/theme with its key', async () => {
    fetchMock.mockResolvedValue(json(200, { ...held, preset: 'oudgeld', revision: 4 }))
    await choose('Oud Geld')
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/theme')
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"preset":"oudgeld"}')
  })

  it('changes nothing locally until the broadcast arrives', async () => {
    fetchMock.mockResolvedValue(json(200, { ...held, preset: 'rood', revision: 4 }))
    await choose('Rood')
    expect(marked()).toEqual(['Paars'])
    act(() => exchangeStore.setState({ theme: { ...held, preset: 'rood', revision: 4 } }))
    expect(marked()).toEqual(['Rood'])
  })

  it('a 403 shows the error and leaves the marked preset', async () => {
    fetchMock.mockResolvedValue(json(403, { error: { code: 'forbidden', message: 'not allowed' } }))
    await choose('Groen')
    expect(screen.getByRole('alert').textContent).toBe('Geen toegang')
    expect(marked()).toEqual(['Paars'])
  })

  it('a network failure shows the connection error', async () => {
    fetchMock.mockRejectedValue(new TypeError('offline'))
    await choose('Blauw')
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
  })

  it('a later success clears the error', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('offline'))
    await choose('Blauw')
    fetchMock.mockResolvedValue(json(200, { ...held, preset: 'blauw', revision: 4 }))
    await choose('Blauw')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

// @vitest-environment jsdom
// `/settings` (Phase 6 T24: SD25, PD13): nine sections, in v1's sidebar order,
// each listed in the section navigation.
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'

const SECTIONS = [
  'Borrel',
  '🧹 Systeemacties',
  '⚙️ Globale instellingen',
  '🎨 Kleurenschema',
  '🖼️ Afbeeldingen',
  '🥤 Drankjes beheren',
  '🔒 Min/Max/Startprijs',
  '📈 Vraag/Aanbod',
  '🔑 Toegangssleutels',
]

beforeEach(() => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'no_current_run', message: 'none' } }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('SettingsPage', () => {
  it('lists the nine sections in the nav, each with its own heading', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    const nav = screen.getByRole('navigation', { name: 'Secties' })
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.textContent),
    ).toEqual(SECTIONS)
    for (const label of SECTIONS) {
      expect(screen.getByRole('heading', { level: 2, name: label })).toBeTruthy()
    }
  })

  it('the sections not built yet say so', async () => {
    render(<SettingsPage />)
    await act(async () => {})

    expect(screen.getAllByText('Nog niet beschikbaar')).toHaveLength(7)
  })
})

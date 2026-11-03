// @vitest-environment jsdom
// `/settings`, the landing page (B-12 T6: SD2, SD10, SD14, SD15, PD7; AC5-AC7):
// the run's status line, then one tile per screen the session may open. It holds
// no settings. The old one-page test's cases live on in `SettingsScreens.test.tsx`.
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../../features/auth'
import { SettingsPage } from './SettingsPage'

const ADMIN = [
  '/',
  '/koers',
  '/bar',
  '/manipulation',
  '/settings',
  '/settings/spel',
  '/settings/wallets',
  '/settings/beheer',
  '/analytics',
  '/kassa',
]

/** SD3's order, SD15's lines. */
const TILES = [
  [
    'Spelopzet',
    'Borrel, profielen, drankjes, prijzen, vraag/aanbod, kleuren, afbeeldingen.',
    '/settings/spel',
  ],
  [
    'Mensen en wallets',
    'Betalen, aanmeldcode, bewaartermijnen, alle wallets.',
    '/settings/wallets',
  ],
  [
    'Beheer',
    'Globale instellingen, vraag/aanbod, toegangssleutels, systeemacties.',
    '/settings/beheer',
  ],
] as const

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

// B-13 SD3, SD4.
const ORGANISER = [
  '/',
  '/koers',
  '/bar',
  '/manipulation',
  '/settings',
  '/settings/spel',
  '/settings/wallets',
  '/kassa',
]
const KASSA = ['/kassa', '/settings', '/settings/wallets']

let role: string
let routes: string[]
let current: () => Response

beforeEach(() => {
  role = 'admin'
  routes = ADMIN
  current = () => json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === '/api/auth/me') {
        return json(200, { role, label: `${role} key`, allowed_routes: routes })
      }
      if (path === '/api/runs/current') return current()
      throw new Error(`unexpected ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function open(path = '/settings') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <SettingsPage />
      </SessionProvider>
    </MemoryRouter>,
  )
  for (let i = 0; i < 3; i += 1) await act(async () => {})
}

const tiles = () => screen.getAllByRole('link')

describe('the landing (AC5)', () => {
  it("shows admin's three screens in SD3's order, each with SD15's line and its address", async () => {
    await open()
    expect(tiles()).toHaveLength(3)
    for (const [i, [name, line, href]] of TILES.entries()) {
      const tile = tiles()[i]
      expect(tile.getAttribute('href')).toBe(href)
      expect(within(tile).getByRole('heading', { level: 2 }).textContent).toBe(name)
      expect(within(tile).getByText(line)).toBeTruthy()
    }
  })

  it('shows only the screens the session may open', async () => {
    routes = ['/settings', '/settings/spel']
    await open()
    expect(tiles().map((tile) => tile.getAttribute('href'))).toEqual(['/settings/spel'])
  })

  it('holds no settings', async () => {
    await open()
    for (const role of ['textbox', 'spinbutton', 'switch', 'combobox', 'checkbox']) {
      expect(screen.queryAllByRole(role)).toEqual([])
    }
  })
})

// B-13 SD14; AC7: the tiles follow `allowed_routes`, and only a session holding
// Spelopzet reads the current run.
describe('per role (B-13)', () => {
  const runCalls = () =>
    vi.mocked(fetch).mock.calls.filter(([path]) => String(path) === '/api/runs/current').length
  const hrefs = () => tiles().map((tile) => tile.getAttribute('href'))

  it('the organiser sees Spelopzet and Mensen en wallets, no Beheer, and the status line', async () => {
    role = 'organiser'
    routes = ORGANISER
    await open()
    expect(hrefs()).toEqual(['/settings/spel', '/settings/wallets'])
    expect(screen.getByText('Borrel: Vrijmibo (live)')).toBeTruthy()
  })

  it('the kassa sees one tile, no status line, and asks for no run', async () => {
    role = 'kassa'
    routes = KASSA
    await open()
    expect(hrefs()).toEqual(['/settings/wallets'])
    for (const text of [/Borrel/, /Laden/, /Geen actieve borrel/]) {
      expect(screen.queryByText(text)).toBeNull()
    }
    expect(runCalls()).toBe(0)
  })

  it('admin sees all three tiles and the status line, as before', async () => {
    await open()
    expect(hrefs()).toEqual(TILES.map(([, , href]) => href))
    expect(screen.getByText('Borrel: Vrijmibo (live)')).toBeTruthy()
    expect(runCalls()).toBe(1)
  })
})

describe('the status line (AC6)', () => {
  it.each([
    [
      'live',
      () => json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }),
      'Borrel: Vrijmibo (live)',
    ],
    [
      'a draft',
      () => json(200, { run_id: 8, name: 'Vrijdag', status: 'draft' }),
      'Borrel: Vrijdag (concept)',
    ],
    [
      'no current run',
      () => json(404, { error: { code: 'no_current_run', message: 'none' } }),
      'Geen actieve borrel',
    ],
    [
      'a failed fetch',
      () => json(500, { error: { code: 'internal', message: 'boom' } }),
      'Borrel: onbekend',
    ],
  ])('reads right for %s, and the tiles still work', async (_case, answer, text) => {
    current = answer
    await open()
    expect(screen.getByText(text)).toBeTruthy()
    expect(tiles().map((tile) => tile.getAttribute('href'))).toEqual(
      TILES.map(([, , href]) => href),
    )
  })

  it('says "Laden…" until the run is known', async () => {
    vi.mocked(fetch).mockImplementation(async (path) =>
      String(path) === '/api/auth/me'
        ? json(200, { role: 'admin', label: 'admin key', allowed_routes: routes })
        : new Promise<Response>(() => {}),
    )
    await open()
    expect(screen.getByText('Laden…')).toBeTruthy()
  })
})

describe('old links (AC7, SD14)', () => {
  it('/settings#borrel shows the landing and scrolls nowhere', async () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    await open('/settings#borrel')
    expect(tiles()).toHaveLength(3)
    expect(document.getElementById('borrel')).toBeNull()
    expect(scrollIntoView).not.toHaveBeenCalled()
    delete (Element.prototype as Partial<Element>).scrollIntoView
  })
})

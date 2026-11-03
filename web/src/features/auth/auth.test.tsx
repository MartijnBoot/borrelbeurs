// @vitest-environment jsdom
// Login and role routing through the real route table, with fetch stubbed
// as the server answers (AC20-AC23, SD4, SD12, SD13).
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../app/routes'
import { renderInDataRouter } from '../../app/testRouter'

// jsdom has no Web Animations API; the board's marquees are tested on their own.
vi.mock('../../components/ui/Marquee', () => ({ Marquee: () => null }))

type Role = 'display' | 'bar' | 'admin' | 'kassa' | 'organiser'

// Phase 3 SD2, as GET /api/auth/me returns it (B-12 SD1: the three settings screens;
// B-13 SD3, SD4: the organiser, and kassa's Mensen en wallets).
const ALLOWED: Record<Role, string[]> = {
  display: ['/koers'],
  bar: ['/bar', '/manipulation'],
  admin: [
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
  ],
  kassa: ['/kassa', '/settings', '/settings/wallets'],
  organiser: [
    '/',
    '/koers',
    '/bar',
    '/manipulation',
    '/settings',
    '/settings/spel',
    '/settings/wallets',
    '/kassa',
  ],
}

const KEYS: Record<string, Role> = {
  'key-display': 'display',
  'key-bar': 'bar',
  'key-admin': 'admin',
  'key-kassa': 'kassa',
  'key-organiser': 'organiser',
}

let session: Role | null
let loginStatus: number | null // force a login failure status

const me = (role: Role) => ({ role, label: `${role} key`, allowed_routes: ALLOWED[role] })
const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
const unauthenticated = () =>
  json(401, { error: { code: 'unauthenticated', message: 'that key is not valid' } })

beforeEach(() => {
  session = null
  loginStatus = null
  // Narrow, so the bar page's revenue chart is not built: jsdom has no canvas.
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (method === 'POST' && path === '/api/auth/login') {
        if (loginStatus === 429) {
          return json(429, { error: { code: 'rate_limited', message: 'too many' } })
        }
        const role = KEYS[JSON.parse(String(init?.body)).key]
        if (loginStatus === 401 || role === undefined) return unauthenticated()
        session = role
        return json(200, me(role))
      }
      if (method === 'GET' && path === '/api/auth/me') {
        return session === null ? unauthenticated() : json(200, me(session))
      }
      if (method === 'POST' && path === '/api/auth/logout') {
        session = null
        return json(204)
      }
      if (method === 'GET' && path === '/api/wallet') {
        return json(401, { error: { code: 'no_wallet', message: 'no wallet' } })
      }
      throw new Error(`unexpected ${method} ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function Where() {
  const location = useLocation()
  return <output data-testid="where">{location.pathname + location.search}</output>
}

const where = () => screen.getByTestId('where').textContent

// B-12 PD1: mounted as main.tsx mounts it, under a data router (the shell's leave guard).
async function open(path: string) {
  renderInDataRouter(
    <>
      <AppRoutes />
      <Where />
    </>,
    [path],
  )
  await act(async () => {})
}

async function logIn(key: string) {
  fireEvent.change(screen.getByLabelText('Toegangscode'), { target: { value: key } })
  fireEvent.click(screen.getByRole('button', { name: 'Inloggen' }))
  await act(async () => {})
}

describe('login (AC21)', () => {
  it.each([
    ['key-display', '/koers'],
    ['key-bar', '/bar'],
    ['key-admin', '/'],
    // B-05 SD7, AC36.
    ['key-kassa', '/kassa'],
    // B-13 SD3, AC5.
    ['key-organiser', '/'],
  ])('%s lands on %s', async (key, landing) => {
    await open('/login')
    await logIn(key)
    expect(where()).toBe(landing)
    expect(screen.getByText('Beurs Borrel')).toBeTruthy()
  })

  it('a wrong key shows v1 failure string', async () => {
    await open('/login')
    await logIn('nope')
    expect(screen.getByRole('alert').textContent).toBe('Ongeldige toegangscode.')
    expect(where()).toBe('/login')
  })

  // B-08 SD10, AC17: one attribute more, nothing else changes.
  it('the key field opens a phone keyboard in capitals, label and button unchanged', async () => {
    await open('/login')
    const field = screen.getByLabelText('Toegangscode')
    expect(field.getAttribute('autocapitalize')).toBe('characters')
    expect(field.getAttribute('placeholder')).toBeNull()
    expect(field.getAttribute('maxlength')).toBeNull()
    expect(screen.getByRole('button', { name: 'Inloggen' })).toBeTruthy()
  })

  it('a malformed key answered 401 shows v1 failure string (B-08 AC17)', async () => {
    await open('/login')
    await logIn('bb_1_' + 'a'.repeat(43))
    expect(screen.getByRole('alert').textContent).toBe('Ongeldige toegangscode.')
    expect(where()).toBe('/login')
  })

  it('a 429 shows the rate-limit string', async () => {
    loginStatus = 429
    await open('/login')
    await logIn('key-admin')
    expect(screen.getByRole('alert').textContent).toBe(
      'Te veel pogingen. Probeer het over een minuut opnieuw.',
    )
  })

  it('a network failure shows v1 connection string', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    await open('/login')
    await logIn('key-admin')
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
  })
})

describe('next (AC20, SD12)', () => {
  it('an unauthenticated visit goes to login with next', async () => {
    await open('/koers')
    expect(where()).toBe('/login?next=%2Fkoers')
  })

  it('is honoured when allowed', async () => {
    await open('/login?next=%2Fmanipulation')
    await logIn('key-bar')
    expect(where()).toBe('/manipulation')
  })

  it('is ignored when not allowed', async () => {
    await open('/login?next=%2Fsettings')
    await logIn('key-display')
    expect(where()).toBe('/koers')
  })

  it('a session lost on the socket restarts the live client after login', async () => {
    const sockets: FakeSocket[] = []
    class FakeSocket {
      onopen: (() => void) | null = null
      onmessage: ((event: { data: unknown }) => void) | null = null
      onclose: ((event: { code: number }) => void) | null = null
      constructor() {
        sockets.push(this)
      }
      send() {}
      close() {}
    }
    vi.stubGlobal('WebSocket', FakeSocket)
    session = 'display'
    await open('/koers')
    expect(sockets).toHaveLength(1)

    session = null
    await act(async () => sockets[0].onclose?.({ code: 4401 }))
    expect(where()).toBe('/login?next=%2Fkoers')

    await logIn('key-display')
    expect(where()).toBe('/koers')
    expect(sockets).toHaveLength(2)
  })

  it('is ignored when it is not a path of this app', async () => {
    await open('/login?next=https%3A%2F%2Fevil.example')
    await logIn('key-admin')
    expect(where()).toBe('/')
  })
})

describe('routes (AC22, AC23, SD4, SD13)', () => {
  it('display on /settings sees "Geen toegang"', async () => {
    session = 'display'
    await open('/settings')
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    expect(where()).toBe('/settings')
  })

  // B-12 AC3: only admin opens the screens (SD17); the address stays. B-13 AC6: the
  // organiser holds neither Beheer nor Analyse, and kassa only Mensen en wallets.
  it.each([
    ...(['display', 'bar'] as const).flatMap((role) =>
      ['/settings/spel', '/settings/wallets', '/settings/beheer'].map((path) => [role, path]),
    ),
    ['kassa', '/settings/spel'],
    ['kassa', '/settings/beheer'],
    ['kassa', '/analytics'],
    ['organiser', '/settings/beheer'],
    ['organiser', '/analytics'],
  ])('%s on %s sees "Geen toegang"', async (role, path) => {
    session = role as Role
    await open(path)
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    expect(where()).toBe(path)
  })

  it('bar on /bar sees the bar page inside the shell (Phase 5 AC28)', async () => {
    session = 'bar'
    await open('/bar')
    expect(screen.getByRole('heading', { name: 'Bar — Bestellen' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Menu/ })).toBeTruthy()
  })

  it('display on /bar sees "Geen toegang" (Phase 5 AC28)', async () => {
    session = 'display'
    await open('/bar')
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Bar — Bestellen' })).toBeNull()
  })

  it('bar on /analytics sees "Geen toegang" and no "Analyse" entry (Phase 7 AC33)', async () => {
    session = 'bar'
    await open('/analytics')
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
    expect(screen.queryByRole('menuitem', { name: 'Analyse' })).toBeNull()
  })

  // B-13 SD9, AC19: what bar sees, without Idle (canEditIdle stays admin's).
  it('an organiser on /manipulation sees the news, events and jump, and no Idle', async () => {
    session = 'organiser'
    await open('/manipulation')
    for (const name of ['Nieuws', 'Market events', 'Price jump']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeTruthy()
    }
    expect(screen.queryByRole('heading', { name: /Idle/ })).toBeNull()
    expect(where()).toBe('/manipulation')
  })

  it('an unknown route sees "Geen toegang" inside the shell', async () => {
    session = 'admin'
    await open('/nergens')
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Menu/ })).toBeTruthy()
  })

  it('logout ends the session and goes to login', async () => {
    session = 'admin'
    await open('/bar')
    fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Uitloggen' }))
    await act(async () => {})
    expect(session).toBeNull()
    expect(where()).toBe('/login')
  })
})

describe('the landing and /speler (B-05 SD20, PD13)', () => {
  const meCalls = () =>
    vi.mocked(fetch).mock.calls.filter(([path]) => String(path) === '/api/auth/me').length

  it('an anonymous / shows the landing choice and stays on /', async () => {
    await open('/')
    expect(screen.getByRole('link', { name: 'Speler' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Crew' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Menu/ })).toBeNull()
    expect(where()).toBe('/')
  })

  it('"Crew" goes to login and a login lands as before', async () => {
    await open('/')
    fireEvent.click(screen.getByRole('link', { name: 'Crew' }))
    await act(async () => {})
    expect(where()).toBe('/login')
    await logIn('key-admin')
    expect(where()).toBe('/')
    expect(screen.getByRole('button', { name: /Menu/ })).toBeTruthy()
  })

  it('an admin / is the home page inside the shell (AC1)', async () => {
    session = 'admin'
    await open('/')
    expect(screen.getByRole('button', { name: /Menu/ })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Speler' })).toBeNull()
  })

  it('a display / still sees "Geen toegang" (AC1)', async () => {
    session = 'display'
    await open('/')
    expect(screen.getByText('Geen toegang')).toBeTruthy()
    expect(where()).toBe('/')
  })

  it('an anonymous /speler asks no /api/auth/me and stays on /speler', async () => {
    await open('/speler')
    expect(meCalls()).toBe(0)
    expect(screen.getByRole('heading', { name: 'Wallet aanmaken' })).toBeTruthy()
    expect(where()).toBe('/speler')
  })

  it('"Speler" on the landing opens sign-up without asking for a session again', async () => {
    await open('/')
    const before = meCalls()
    fireEvent.click(screen.getByRole('link', { name: 'Speler' }))
    await act(async () => {})
    expect(where()).toBe('/speler')
    expect(meCalls()).toBe(before)
    expect(screen.getByRole('heading', { name: 'Wallet aanmaken' })).toBeTruthy()
  })
})

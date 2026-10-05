// @vitest-environment jsdom
// Login and role routing through the real route table, with fetch stubbed
// as the server answers (AC20-AC23, SD4, SD12, SD13).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../app/routes'

type Role = 'display' | 'bar' | 'admin'

// Phase 3 SD2, as GET /api/auth/me returns it.
const ALLOWED: Record<Role, string[]> = {
  display: ['/koers'],
  bar: ['/bar', '/manipulation'],
  admin: ['/', '/koers', '/bar', '/manipulation', '/settings'],
}

const KEYS: Record<string, Role> = {
  'key-display': 'display',
  'key-bar': 'bar',
  'key-admin': 'admin',
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

async function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <Where />
    </MemoryRouter>,
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

  it('bar on /bar sees the placeholder inside the shell', async () => {
    session = 'bar'
    await open('/bar')
    expect(screen.getByText('Nog niet beschikbaar')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Menu/ })).toBeTruthy()
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

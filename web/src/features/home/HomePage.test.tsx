// @vitest-environment jsdom
// Home (Phase 6 T35: SD31, PD14; AC41, AC25): v1's four tiles and the live
// "Status" panel -- socket, run, server health and connections per role.
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { HomePage } from './HomePage'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const LIVE = { run_id: 7, name: 'Vrijmibo', status: 'live' }
const HEALTH = { status: 'ok', last_tick_age_ms: 400, last_commit_age_ms: 900 }
const BAR = { role: 'bar', label: 'Tap 1', connected_at_ms: 0, last_seen_ms: 0 }
const DISPLAY = { role: 'display', label: 'Scherm', connected_at_ms: 0, last_seen_ms: 0 }

// Vitest runs in Node; `src/` has no Node types, so the one call this file needs is typed here.
type Listener = (reason: unknown) => void
const node = (
  globalThis as unknown as {
    process: { on(e: string, l: Listener): void; off(e: string, l: Listener): void }
  }
).process

let connections: unknown[]
let run: () => Response
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  connections = [BAR]
  run = () => json(200, LIVE)
  fetchMock = vi.fn((path: string) => {
    if (path === '/api/runs/current') return Promise.resolve(run())
    if (path === '/healthz') return Promise.resolve(json(200, HEALTH))
    if (path === '/api/admin/connections') return Promise.resolve(json(200, connections))
    return Promise.resolve(json(404, { error: { code: 'not_found', message: path } }))
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function settle() {
  for (let i = 0; i < 4; i += 1) await act(async () => {})
}

async function open() {
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  )
  await settle()
}

const status = () => screen.getByRole('region', { name: 'Status' })
const calls = (path: string) => fetchMock.mock.calls.filter(([p]) => p === path).length

describe('HomePage', () => {
  it("shows v1's four tiles, drinks and shutdown on settings (SD31)", async () => {
    await open()
    for (const [name, href] of [
      ['Live koersbord', '/koers'],
      ['Bar', '/bar'],
      ['Spel mechanica', '/manipulation'],
      ['Instellingen', '/settings'],
    ]) {
      expect(screen.getByRole('link', { name: new RegExp(name) }).getAttribute('href')).toBe(href)
    }
    const blurbs = [
      'Globale instellingen, grenzen, vraag/aanbod, drankjes, afsluiten.',
      'Price jumps, nieuws, idle, reset.',
    ]
    for (const blurb of blurbs) expect(screen.getByText(blurb)).toBeTruthy()
  })

  it('shows the socket, the run and the server health', async () => {
    act(() => exchangeStore.setState({ status: 'open' }))
    await open()
    expect(within(status()).getByText(/Verbonden/)).toBeTruthy()
    expect(within(status()).getByText(/Vrijmibo/)).toBeTruthy()
    expect(within(status()).getByText(/laatste tick 0,4 s geleden/)).toBeTruthy()
    expect(within(status()).getByText(/Server: ok/)).toBeTruthy()
  })

  it('says "Geen actieve borrel" without a current run', async () => {
    run = () => json(404, { error: { code: 'no_current_run', message: 'none' } })
    await open()
    expect(within(status()).getByText('Geen actieve borrel')).toBeTruthy()
  })

  it('a live run with no display connected warns "Koersbord niet verbonden"', async () => {
    await open()
    expect(within(status()).getByText('Koersbord niet verbonden')).toBeTruthy()
  })

  it('with a display connected, the warning is gone', async () => {
    connections = [BAR, DISPLAY]
    await open()
    expect(within(status()).queryByText('Koersbord niet verbonden')).toBeNull()
    expect(within(status()).getByText(/Scherm: 1/)).toBeTruthy()
  })

  it('polls health and connections every 5 s, and stops on unmount', async () => {
    vi.useFakeTimers()
    await open()
    expect(calls('/healthz')).toBe(1)
    expect(calls('/api/admin/connections')).toBe(1)

    await act(async () => vi.advanceTimersByTime(4_999))
    expect(calls('/healthz')).toBe(1)
    await act(async () => vi.advanceTimersByTime(1))
    expect(calls('/healthz')).toBe(2)
    expect(calls('/api/admin/connections')).toBe(2)

    cleanup()
    await act(async () => vi.advanceTimersByTime(20_000))
    expect(calls('/healthz')).toBe(2)
  })

  it('a rejected fetch is caught: no unhandled rejection', async () => {
    const unhandled = vi.fn()
    node.on('unhandledRejection', unhandled)
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('offline')))
    try {
      await open()
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(unhandled).not.toHaveBeenCalled()
      expect(within(status()).getByText(/Server: onbereikbaar/)).toBeTruthy()
    } finally {
      node.off('unhandledRejection', unhandled)
    }
  })
})

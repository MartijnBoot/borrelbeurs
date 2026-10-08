// @vitest-environment jsdom
// 🧹 Systeemacties (Phase 6 T29: SD26; AC39): shutdown behind a dialog, and
// anchor-s0 with none, as in v1. No reset, no export.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { SystemSection } from './SystemSection'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>
let status: 'live' | 'draft'

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  status = 'live'
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status }))
    }
    if (path === '/api/admin/shutdown')
      return Promise.resolve(json(202, { status: 'shutting_down' }))
    if (init?.method === 'POST') return Promise.resolve(json(200, { revision: 5 }))
    return Promise.resolve(json(404, { error: { code: 'not_found', message: 'x' } }))
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

const posts = () =>
  (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => init?.method === 'POST')
    .map(([path]) => path)

async function open() {
  render(<SystemSection />)
  await settle()
}

describe('SystemSection', () => {
  it('shutdown asks first: Cancel sends nothing', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: '⛔ Sluit app' }))
    expect(screen.getByRole('dialog', { name: 'Applicatie nu afsluiten?' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(posts()).toEqual([])
  })

  it('Confirm posts shutdown, says so, and disables every button', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: '⛔ Sluit app' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(posts()).toEqual(['/api/admin/shutdown'])
    expect(screen.getByText('App sluit nu af…')).toBeTruthy()
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(true)
    }
  })

  it('anchor-s0 posts once, with no dialog', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: '📌 Zet huidige prijs als evenwicht' }))
    await settle()

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(posts()).toEqual(['/api/runs/7/anchor-s0'])
  })

  it('anchor-s0 is disabled for a draft', async () => {
    status = 'draft'
    await open()
    const anchor = screen.getByRole('button', { name: '📌 Zet huidige prijs als evenwicht' })
    expect((anchor as HTMLButtonElement).disabled).toBe(true)
  })

  it('offers no reset and no export', async () => {
    await open()
    expect(screen.queryByRole('button', { name: /reset/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /download|export/i })).toBeNull()
  })
})

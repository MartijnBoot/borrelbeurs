// @vitest-environment jsdom
// `/speler` (B-05 SD20, SD21; AC13): sign-up without a wallet, the wallet with one.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PlayerPage } from './PlayerPage'

const WALLET = {
  name: 'Jan',
  balance_cents: 1500,
  qr_token: 'tok-1',
  short_code: 'K7Q4-M2XD',
  created_at: '2026-10-25T10:00:00Z',
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const noWallet = () => json(401, { error: { code: 'no_wallet', message: 'no wallet' } })

let answers: (() => Response)[]

beforeEach(() => {
  answers = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => (answers.shift() ?? (() => json(200, WALLET)))()),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function open() {
  render(
    <MemoryRouter initialEntries={['/speler']}>
      <PlayerPage />
    </MemoryRouter>,
  )
  await act(async () => {})
}

describe('PlayerPage', () => {
  it('a 401 no_wallet shows sign-up (AC13)', async () => {
    answers = [noWallet]
    await open()
    expect(screen.getByRole('heading', { name: 'Wallet aanmaken' })).toBeTruthy()
  })

  it('a wallet cookie shows the wallet', async () => {
    await open()
    expect(screen.getByRole('heading', { name: 'Jan' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Wallet aanmaken' })).toBeNull()
  })

  it('a sign-up shows the new wallet (AC3)', async () => {
    answers = [noWallet, () => json(201, { ...WALLET, name: 'Piet', balance_cents: 0 })]
    await open()
    fireEvent.change(screen.getByLabelText('Naam'), { target: { value: 'Piet' } })
    fireEvent.change(screen.getByLabelText('Aanmeldcode'), { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aanmelden' }))
    await act(async () => {})
    expect(screen.getByRole('heading', { name: 'Piet' })).toBeTruthy()
  })

  it('a refresh shows a served name change and a new code (AC26, AC28)', async () => {
    await open()
    answers = [() => json(200, { ...WALLET, name: 'Jan 2', short_code: 'AAAA-BBBB' })]
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(screen.getByRole('heading', { name: 'Jan 2' })).toBeTruthy()
    expect(screen.getByText('AAAA-BBBB')).toBeTruthy()
  })

  it('a 401 on a refresh shows sign-up (AC13)', async () => {
    await open()
    answers = [noWallet]
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(screen.getByRole('heading', { name: 'Wallet aanmaken' })).toBeTruthy()
  })

  it('a failed refresh keeps the wallet shown', async () => {
    await open()
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(screen.getByRole('heading', { name: 'Jan' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a network failure offers a retry', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    await open()
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
    fireEvent.click(screen.getByRole('button', { name: 'Opnieuw' }))
    await act(async () => {})
    expect(screen.getByRole('heading', { name: 'Jan' })).toBeTruthy()
  })
})

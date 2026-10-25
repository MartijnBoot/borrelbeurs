// @vitest-environment jsdom
// The kassa page (B-05 SD22; AC14, AC15): a typed code, the found wallet, a top-up.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { KassaPage } from './KassaPage'

const JAN = {
  wallet_id: 7,
  name: 'Jan',
  balance_cents: 1500,
  created_at: '2026-10-25T18:00:00Z',
  last_topup_at: '2026-10-25T19:00:00Z',
  recent_topup: null,
}
const TOPUPS = [
  {
    entry_id: 2,
    amount_cents: 1500,
    created_at: '2026-10-25T19:00:00Z',
    actor_label: 'Kassa 1',
    reversed: false,
  },
  {
    entry_id: 1,
    amount_cents: 1000,
    created_at: '2026-10-25T18:30:00Z',
    actor_label: 'Kassa 1',
    reversed: true,
  },
]

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let balance: number

beforeEach(() => {
  balance = 1500
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/kassa/lookup') {
        const body = JSON.parse(String(init?.body))
        if (body.short_code === 'ZZZZ-ZZZZ') {
          return json(404, { error: { code: 'wallet_not_found', message: 'no' } })
        }
        return json(200, { ...JAN, balance_cents: balance })
      }
      if (path === '/api/kassa/wallets/7/topups' && init?.method === 'POST') {
        balance += 1000
        return json(201, { entry_id: 3, wallet_id: 7, amount_cents: 1000, created_at: 'x' })
      }
      if (path === '/api/kassa/wallets/7/topups') return json(200, TOPUPS)
      throw new Error(`unexpected ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function find(code: string) {
  fireEvent.change(screen.getByLabelText('Code typen'), { target: { value: code } })
  fireEvent.click(screen.getByRole('button', { name: 'Zoeken' }))
  await act(async () => {})
}

const lookups = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(([path]) => path === '/api/kassa/lookup')
    .map(([, init]) => JSON.parse(String(init?.body)))

describe('KassaPage', () => {
  it('sends the code exactly as typed and shows the wallet, its balance and top-ups (AC14)', async () => {
    render(<KassaPage />)
    await find(' k7q4 m2xd ')
    expect(lookups()).toEqual([{ short_code: ' k7q4 m2xd ' }])
    const card = screen.getByRole('region', { name: 'Jan' })
    expect(within(card).getByRole('heading', { name: 'Jan' })).toBeTruthy()
    expect(card.textContent).toContain(formatEuro(1500))
    const rows = within(screen.getByRole('list', { name: 'Opwaarderingen' })).getAllByRole(
      'listitem',
    )
    expect(rows.map((row) => row.textContent?.includes('teruggedraaid'))).toEqual([false, true])
  })

  it('an unknown code is "Onbekende wallet" (AC14)', async () => {
    render(<KassaPage />)
    await find('ZZZZ-ZZZZ')
    expect(screen.getByRole('alert').textContent).toBe('Onbekende wallet')
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('a top-up looks the wallet up again and shows the new balance (AC15)', async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Opwaarderen' }))
    await act(async () => {})
    expect(lookups()).toHaveLength(2)
    expect(screen.getByRole('region', { name: 'Jan' }).textContent).toContain(formatEuro(2500))
  })

  it('an empty field asks nothing', async () => {
    render(<KassaPage />)
    await find('   ')
    expect(fetch).not.toHaveBeenCalled()
  })
})

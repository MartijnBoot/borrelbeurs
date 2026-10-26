// @vitest-environment jsdom
// The Wallets section (B-05 SD6, SD15, SD16; AC30, AC33, AC34; PD2, PD12, PD20).
// B-06 SD20, PD10, PD18: "Tegoed" and "Rood", payments per borrel, debt (AC25, AC30).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatBalance, formatEuro } from '../../lib/format'
import { formatDayMonth } from '../../lib/time'
import { WalletsSection } from './WalletsSection'

const OVERVIEW = {
  positive_balance_cents: 5000,
  negative_balance_cents: -350,
  per_borrel: [
    { run_id: 8, name: 'Novemberborrel', net_topup_cents: 3500, net_payment_cents: 1240 },
    { run_id: 7, name: 'Oktoberborrel', net_topup_cents: 1000, net_payment_cents: 0 },
    { run_id: null, name: null, net_topup_cents: 1500, net_payment_cents: 0 },
  ],
  wallets: [
    { wallet_id: 1, name: 'alpha', balance_cents: 0, last_activity_at: '2026-10-20T19:00:00Z' },
    { wallet_id: 2, name: 'Beta', balance_cents: 3500, last_activity_at: '2026-10-25T19:00:00Z' },
    { wallet_id: 3, name: 'Gamma', balance_cents: -350, last_activity_at: '2026-10-25T20:00:00Z' },
  ],
}
const STORED = { signup_code: 'Borrel2026', unfunded_days: 30, inactive_months: 12 }

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let overview: typeof OVERVIEW
let stored: typeof STORED | { signup_code: null; unfunded_days: number; inactive_months: number }
let putAnswer: ((body: typeof STORED) => Response) | null

beforeEach(() => {
  overview = OVERVIEW
  stored = STORED
  putAnswer = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (path === '/api/admin/wallets' && method === 'GET') return json(200, overview)
      if (path === '/api/admin/wallet-settings' && method === 'GET') return json(200, stored)
      if (path === '/api/admin/wallet-settings' && method === 'PUT') {
        const body = JSON.parse(String(init?.body))
        if (putAnswer !== null) return putAnswer(body)
        stored = { ...body, signup_code: body.signup_code?.trim() || null }
        return json(200, stored)
      }
      if (path.startsWith('/api/admin/wallets/') && method === 'DELETE') {
        overview = { ...overview, wallets: overview.wallets.slice(1) }
        return new Response(null, { status: 204 })
      }
      throw new Error(`unexpected ${method} ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function open() {
  render(<WalletsSection />)
  await act(async () => {})
}

const region = (name: string) => screen.getByRole('region', { name })
const puts = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method === 'PUT')
    .map(([, init]) => JSON.parse(String(init?.body)))

async function click(scope: HTMLElement, name: string) {
  fireEvent.click(within(scope).getByRole('button', { name }))
  await act(async () => {})
}

describe('Aanmeldcode (SD6, PD12, PD20)', () => {
  it('shows the code and the poster link built from it', async () => {
    await open()
    const code = region('Aanmeldcode')
    expect((within(code).getByLabelText('Aanmeldcode') as HTMLInputElement).value).toBe(
      'Borrel2026',
    )
    expect(within(code).getByText(`${window.location.origin}/speler?code=Borrel2026`)).toBeTruthy()
  })

  it('"Opslaan" sends the typed code with the stored periods', async () => {
    await open()
    const code = region('Aanmeldcode')
    fireEvent.change(within(code).getByLabelText('Aanmeldcode'), { target: { value: 'Nieuw' } })
    await click(code, 'Opslaan')
    expect(puts()).toEqual([{ signup_code: 'Nieuw', unfunded_days: 30, inactive_months: 12 }])
    expect(within(code).getByText(`${window.location.origin}/speler?code=Nieuw`)).toBeTruthy()
  })

  it('"Wissen" sends null and says sign-up is closed (AC34)', async () => {
    await open()
    const code = region('Aanmeldcode')
    await click(code, 'Wissen')
    expect(puts()).toEqual([{ signup_code: null, unfunded_days: 30, inactive_months: 12 }])
    expect(within(code).getByText('Aanmelden is gesloten.')).toBeTruthy()
    expect((within(code).getByLabelText('Aanmeldcode') as HTMLInputElement).value).toBe('')
  })

  it('no code set says sign-up is closed', async () => {
    stored = { signup_code: null, unfunded_days: 30, inactive_months: 12 }
    await open()
    expect(within(region('Aanmeldcode')).getByText('Aanmelden is gesloten.')).toBeTruthy()
  })
})

describe('Bewaartermijnen (AC33)', () => {
  it('sends both periods as numbers', async () => {
    await open()
    const periods = region('Bewaartermijnen')
    fireEvent.change(within(periods).getByLabelText(/dagen/), { target: { value: '7' } })
    fireEvent.change(within(periods).getByLabelText(/maanden/), { target: { value: '3' } })
    await click(periods, 'Opslaan')
    expect(puts()).toEqual([{ signup_code: 'Borrel2026', unfunded_days: 7, inactive_months: 3 }])
  })

  it('a 422 names the ranges', async () => {
    putAnswer = () => json(422, { error: { code: 'validation_error', message: 'no' } })
    await open()
    const periods = region('Bewaartermijnen')
    fireEvent.change(within(periods).getByLabelText(/dagen/), { target: { value: '366' } })
    await click(periods, 'Opslaan')
    expect(within(periods).getByRole('alert').textContent).toBe('Kies 1–365 dagen en 1–60 maanden.')
  })
})

describe('Totalen (AC34, PD2; B-06 AC30, PD10)', () => {
  it('shows "Tegoed" and "Rood" apart, and each borrel, newest first, then "Zonder borrel"', async () => {
    await open()
    const totals = region('Totalen')
    expect(totals.textContent).toContain(`Tegoed: ${formatEuro(5000)}`)
    expect(totals.textContent).toContain('Rood: −€ 3,50')
    expect(
      within(totals)
        .getAllByRole('listitem')
        .map((row) => row.textContent),
    ).toEqual([
      `Novemberborrel: opgewaardeerd ${formatEuro(3500)}, besteed ${formatEuro(1240)}`,
      `Oktoberborrel: opgewaardeerd ${formatEuro(1000)}, besteed ${formatEuro(0)}`,
      `Zonder borrel: opgewaardeerd ${formatEuro(1500)}, besteed ${formatEuro(0)}`,
    ])
    expect(totals.textContent).not.toMatch(/omzet|opbrengst|verdien/i)
  })
})

describe('the list (AC30, AC34)', () => {
  it('shows each wallet with its balance and last activity, in the served order', async () => {
    await open()
    const rows = within(region('Alle wallets')).getAllByRole('listitem')
    expect(rows.map((row) => row.querySelector('strong')?.textContent)).toEqual([
      'alpha',
      'Beta',
      'Gamma',
    ])
    expect(rows[1].textContent).toContain(formatEuro(3500))
    expect(rows[2].textContent).toContain(formatBalance(-350))
    expect(rows[2].textContent).toContain('−€ 3,50')
    expect(rows[1].textContent).toContain(
      `laatst actief ${formatDayMonth(Date.parse('2026-10-25T19:00:00Z'))}`,
    )
  })

  it('"Verwijderen" asks with the balance that is lost, then deletes and reloads', async () => {
    await open()
    const [first] = within(region('Alle wallets')).getAllByRole('listitem')
    fireEvent.click(within(first).getByRole('button', { name: 'Verwijderen' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `Wallet 'alpha' verwijderen? Het saldo van ${formatEuro(0)} vervalt.`,
    )
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Verwijderen' }))
    await act(async () => {})

    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([path, init]) => path === '/api/admin/wallets/1' && init?.method === 'DELETE',
        ),
    ).toBe(true)
    expect(
      within(region('Alle wallets'))
        .getAllByRole('listitem')
        .map((row) => row.querySelector('strong')?.textContent),
    ).toEqual(['Beta', 'Gamma'])
  })

  it('a wallet in debt asks with the debt that is written off (PD18)', async () => {
    await open()
    const rows = within(region('Alle wallets')).getAllByRole('listitem')
    fireEvent.click(within(rows[2]).getByRole('button', { name: 'Verwijderen' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `Wallet 'Gamma' verwijderen? De schuld van ${formatEuro(350)} vervalt.`,
    )
  })

  it('cancel deletes nothing', async () => {
    await open()
    const [first] = within(region('Alle wallets')).getAllByRole('listitem')
    fireEvent.click(within(first).getByRole('button', { name: 'Verwijderen' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('no wallets says so', async () => {
    overview = {
      ...OVERVIEW,
      positive_balance_cents: 0,
      negative_balance_cents: 0,
      per_borrel: [],
      wallets: [],
    }
    await open()
    expect(within(region('Alle wallets')).getByText('Nog geen wallets')).toBeTruthy()
    expect(within(region('Totalen')).queryByRole('list')).toBeNull()
  })
})

describe('a failed load', () => {
  it('shows the connection text', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('offline'))
    await open()
    expect(screen.getByText('Verbindingsfout. Probeer opnieuw.')).toBeTruthy()
  })
})

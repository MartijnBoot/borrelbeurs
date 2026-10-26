// @vitest-environment jsdom
// The bar's recent payments and their refund (B-06 T15: SD9; AC20-AC22; PD16, PD18).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { formatHourMinute } from '../../lib/time'
import { PAYMENTS_REFRESH_MS } from './model/constants'
import { RecentPayments } from './RecentPayments'

const AT = '2026-10-26T20:15:00Z'
const PAID = {
  entry_id: 41,
  amount_cents: 840,
  created_at: AT,
  lines: [
    { name: 'Bier', qty: 2 },
    { name: 'Wijn', qty: 1 },
  ],
  refunded: false,
  name: 'Jan',
}
const DONE = {
  ...PAID,
  entry_id: 40,
  amount_cents: 250,
  lines: [{ name: 'Bier', qty: 1 }],
  refunded: true,
  name: null,
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let listed: unknown[]
let refundAnswer: () => Promise<Response>

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  listed = [PAID, DONE]
  refundAnswer = async () => {
    listed = [{ ...PAID, refunded: true }, DONE]
    return json(201, { entry_id: 42, wallet_id: 7, amount_cents: 840, created_at: AT })
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/bar/payments' && (init?.method ?? 'GET') === 'GET')
        return json(200, listed)
      if (path === '/api/payments/41/refund' && init?.method === 'POST') return refundAnswer()
      throw new Error(`unexpected ${init?.method} ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const settle = () => act(async () => {})
const gets = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(
      ([path, init]) => path === '/api/bar/payments' && (init?.method ?? 'GET') === 'GET',
    ).length
const posts = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')
const keyOf = (call: ReturnType<typeof posts>[number]) =>
  new Headers(call[1]?.headers).get('Idempotency-Key')
const section = () => screen.getByRole('region', { name: 'Betalingen (laatste 10 minuten)' })
const rows = () => within(section()).getAllByRole('listitem')

async function open(lastPaid = 0) {
  const view = render(<RecentPayments lastPaid={lastPaid} />)
  await settle()
  return view
}

async function refundFirst() {
  fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugboeken' }))
  await settle()
}

describe('RecentPayments', () => {
  it("lists each payment's lines, amount, time and name, and whether refunded (AC20)", async () => {
    await open()
    expect(section().querySelector('h3')?.textContent).toBe('Betalingen (laatste 10 minuten)')
    const [first, second] = rows()
    const at = formatHourMinute(Date.parse(AT))
    expect(first.textContent).toContain(`2× Bier, 1× Wijn — ${formatEuro(840)} om ${at}, Jan`)
    expect(within(first).getByRole('button', { name: 'Terugboeken' })).toBeTruthy()
    expect(second.textContent).toContain(
      `1× Bier — ${formatEuro(250)} om ${at}, verwijderde wallet`,
    )
    expect(second.textContent).toContain('teruggeboekt')
    expect(within(second).queryByRole('button')).toBeNull()
  })

  it('says so when there are none', async () => {
    listed = []
    await open()
    expect(within(section()).getByText('Nog geen betalingen')).toBeTruthy()
  })

  it('fetches on mount, after a paid order, and every 30 s; never filters by its clock (PD16)', async () => {
    const view = await open()
    expect(gets()).toBe(1)
    view.rerender(<RecentPayments lastPaid={3} />)
    await settle()
    expect(gets()).toBe(2)
    view.rerender(<RecentPayments lastPaid={3} />)
    await settle()
    expect(gets()).toBe(2)
    expect(PAYMENTS_REFRESH_MS).toBe(30_000)
    await act(() => vi.advanceTimersByTimeAsync(PAYMENTS_REFRESH_MS))
    expect(gets()).toBe(3)
  })

  it('confirms with the amount and the name, posts under a fresh key, and fetches again (AC21)', async () => {
    await open()
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `${formatEuro(840)} terugboeken naar Jan?`,
    )
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugboeken' }))
    await settle()
    expect(posts()).toHaveLength(1)
    expect(keyOf(posts()[0])).toMatch(/^[0-9a-f]{32}$/)
    expect(gets()).toBe(2)
    expect(rows()[0].textContent).toContain('teruggeboekt')
  })

  it('cancel sends nothing', async () => {
    await open()
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    await settle()
    expect(posts()).toHaveLength(0)
  })

  it.each([
    ['already_refunded', 409, 'Deze betaling is al teruggeboekt.'],
    ['refund_not_allowed', 403, 'Terugboeken kan hier alleen binnen 10 minuten na de betaling.'],
    ['wallet_deleted', 409, 'Deze wallet bestaat niet meer.'],
  ])('a %s says so (AC22, PD18)', async (code, status, text) => {
    refundAnswer = async () => json(status, { error: { code, message: 'no' } })
    await open()
    await refundFirst()
    expect(within(section()).getByRole('alert').textContent).toBe(text)
    expect(within(section()).queryByRole('button', { name: 'Opnieuw' })).toBeNull()
  })

  it('a network failure keeps the key for "Opnieuw" (B-05 /review C1)', async () => {
    refundAnswer = async () => Promise.reject(new TypeError('Failed to fetch'))
    await open()
    await refundFirst()
    expect(within(section()).getByRole('alert').textContent).toBe(
      'Verbindingsfout. Probeer opnieuw.',
    )
    expect(
      within(section())
        .getAllByRole('button', { name: 'Terugboeken' })
        .every((b) => (b as HTMLButtonElement).disabled),
    ).toBe(true)
    refundAnswer = async () =>
      json(201, { entry_id: 42, wallet_id: 7, amount_cents: 840, created_at: AT })
    fireEvent.click(within(section()).getByRole('button', { name: 'Opnieuw' }))
    await settle()
    expect(posts()).toHaveLength(2)
    expect(keyOf(posts()[1])).toBe(keyOf(posts()[0]))
    expect(within(section()).queryByRole('alert')).toBeNull()
  })
})

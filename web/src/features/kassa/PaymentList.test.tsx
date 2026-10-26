// @vitest-environment jsdom
// A found wallet's payments at the kassa (B-06 T16: SD9; AC23; PD18).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { formatDayMonthTime } from '../../lib/time'
import type { Payment } from './api'
import { PaymentList } from './PaymentList'

const AT = '2026-10-20T20:15:00Z'
const PAID: Payment = {
  entry_id: 41,
  amount_cents: 840,
  created_at: AT,
  lines: [
    { name: 'Bier', qty: 2 },
    { name: 'Wijn', qty: 1 },
  ],
  refunded: false,
  actor_label: 'Bar 1',
}
const GONE: Payment = { ...PAID, entry_id: 40, amount_cents: 250, lines: null, refunded: true }

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let answer: () => Promise<Response>
let refunded: number

beforeEach(() => {
  refunded = 0
  answer = async () => json(201, { entry_id: 42, wallet_id: 7, amount_cents: 840, created_at: AT })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/payments/41/refund' && init?.method === 'POST') return answer()
      throw new Error(`unexpected ${init?.method} ${path}`)
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const posts = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')
const rows = () => within(screen.getByRole('list', { name: 'Betalingen' })).getAllByRole('listitem')

function open(payments: Payment[] = [PAID, GONE]) {
  render(<PaymentList walletName="Jan" payments={payments} onRefunded={() => (refunded += 1)} />)
}

async function refundFirst() {
  fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugboeken' }))
  await act(async () => {})
}

describe('PaymentList', () => {
  it('lists each payment with its lines, amount, time and key, or "teruggeboekt" (AC23)', () => {
    open()
    expect(screen.getByRole('heading', { name: 'Betalingen' })).toBeTruthy()
    const [first, second] = rows()
    const at = formatDayMonthTime(Date.parse(AT))
    expect(first.textContent).toContain(`2× Bier, 1× Wijn — ${formatEuro(840)} op ${at}, Bar 1`)
    expect(within(first).getByRole('button', { name: 'Terugboeken' })).toBeTruthy()
    expect(second.textContent).toContain(`Bestelling niet meer beschikbaar — ${formatEuro(250)}`)
    expect(second.textContent).toContain('teruggeboekt')
    expect(within(second).queryByRole('button')).toBeNull()
  })

  it('says so when there are none', () => {
    open([])
    expect(screen.getByText('Nog geen betalingen')).toBeTruthy()
  })

  it('confirms with the amount, posts under a fresh key, then reloads (AC23)', async () => {
    open()
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `${formatEuro(840)} terugboeken naar Jan?`,
    )
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugboeken' }))
    await act(async () => {})
    expect(posts()).toHaveLength(1)
    expect(new Headers(posts()[0][1]?.headers).get('Idempotency-Key')).toMatch(/^[0-9a-f]{32}$/)
    expect(refunded).toBe(1)
  })

  it('cancel sends nothing', () => {
    open()
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Terugboeken' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(posts()).toHaveLength(0)
  })

  it.each([
    ['already_refunded', 409, 'Deze betaling is al teruggeboekt.'],
    ['wallet_deleted', 409, 'Deze wallet bestaat niet meer.'],
    ['payment_not_found', 404, 'Verbindingsfout. Probeer opnieuw.'],
  ])('a %s says so (PD18)', async (code, status, text) => {
    answer = async () => json(status, { error: { code, message: 'no' } })
    open()
    await refundFirst()
    expect(screen.getByRole('alert').textContent).toBe(text)
    expect(refunded).toBe(0)
  })

  it('a network failure says so', async () => {
    answer = async () => Promise.reject(new TypeError('Failed to fetch'))
    open()
    await refundFirst()
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
  })
})

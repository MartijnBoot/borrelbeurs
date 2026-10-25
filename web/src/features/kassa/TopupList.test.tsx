// @vitest-environment jsdom
// Reversing a top-up (B-05 SD12; AC21, AC22; PD15).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { formatDayMonthTime } from '../../lib/time'
import { TopupList } from './TopupList'

const TOPUPS = [
  {
    entry_id: 12,
    amount_cents: 1500,
    created_at: '2026-10-25T19:00:00Z',
    actor_label: 'Kassa 1',
    reversed: false,
  },
  {
    entry_id: 11,
    amount_cents: 1000,
    created_at: '2026-10-25T18:30:00Z',
    actor_label: 'Bestuur',
    reversed: true,
  },
]

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const refusal = (code: string) => json(409, { error: { code, message: code } })

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      json(201, { entry_id: 13, wallet_id: 7, amount_cents: -1500, created_at: 'x' }),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function show(onReversed = vi.fn()) {
  render(<TopupList topups={TOPUPS} onReversed={onReversed} />)
  return onReversed
}

async function reverseFirst() {
  fireEvent.click(screen.getByRole('button', { name: 'Terugdraaien' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugdraaien' }))
  await act(async () => {})
}

describe('TopupList', () => {
  it('lists each top-up, and offers "Terugdraaien" only on one not yet reversed', () => {
    show()
    const rows = screen.getAllByRole('listitem')
    expect(rows[0].textContent).toContain(formatEuro(1500))
    expect(rows[0].textContent).toContain('Kassa 1')
    expect(within(rows[0]).getByRole('button', { name: 'Terugdraaien' })).toBeTruthy()
    expect(rows[1].textContent).toContain('teruggedraaid')
    expect(within(rows[1]).queryByRole('button')).toBeNull()
  })

  it('asks "<€X> van <datum> terugdraaien?" and posts with a fresh key (AC21)', async () => {
    const onReversed = show()
    fireEvent.click(screen.getByRole('button', { name: 'Terugdraaien' }))
    const when = formatDayMonthTime(Date.parse(TOPUPS[0].created_at))
    expect(screen.getByRole('dialog').textContent).toContain(
      `${formatEuro(1500)} van ${when} terugdraaien?`,
    )
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugdraaien' }),
    )
    await act(async () => {})

    const [[path, init]] = vi.mocked(fetch).mock.calls
    expect(path).toBe('/api/kassa/topups/12/reversal')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBeUndefined()
    expect((init?.headers as Record<string, string>)['Idempotency-Key']).toMatch(/^[0-9a-f]{32}$/)
    expect(onReversed).toHaveBeenCalledTimes(1)
  })

  it('cancel sends nothing', () => {
    const onReversed = show()
    fireEvent.click(screen.getByRole('button', { name: 'Terugdraaien' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(fetch).not.toHaveBeenCalled()
    expect(onReversed).not.toHaveBeenCalled()
  })

  it.each([
    ['already_reversed', 'Deze opwaardering is al teruggedraaid.'],
    ['insufficient_balance', 'Te weinig saldo om terug te draaien.'],
    ['wallet_deleted', 'Deze wallet bestaat niet meer.'],
  ])('a 409 %s says so in Dutch (AC22)', async (code, text) => {
    vi.mocked(fetch).mockResolvedValueOnce(refusal(code))
    const onReversed = show()
    await reverseFirst()
    expect(screen.getByRole('alert').textContent).toBe(text)
    expect(onReversed).not.toHaveBeenCalled()
  })

  it('an empty list says so', () => {
    render(<TopupList topups={[]} onReversed={vi.fn()} />)
    expect(screen.getByText('Nog geen opwaarderingen')).toBeTruthy()
  })
})

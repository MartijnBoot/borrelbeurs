// @vitest-environment jsdom
// Moving a balance (B-05 SD11; AC25-AC27; PD15, PD17).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { formatDayMonth, formatDayMonthTime } from '../../lib/time'
import type { KassaWallet } from './api'
import { MoveDialog } from './MoveDialog'

const OPEN: KassaWallet = {
  wallet_id: 9,
  name: 'Jan 2',
  balance_cents: 0,
  created_at: '2026-10-25T20:00:00Z',
  last_topup_at: null,
  recent_topup: null,
}

const FOUND = [
  {
    wallet_id: 4,
    name: 'Jan',
    created_at: '2026-09-12T18:00:00Z',
    balance_cents: 1500,
    last_topup_at: '2026-10-24T19:30:00Z',
  },
  {
    wallet_id: 9,
    name: 'Jan 2',
    created_at: '2026-10-25T20:00:00Z',
    balance_cents: 0,
    last_topup_at: null,
  },
  {
    wallet_id: 5,
    name: 'Janneke',
    created_at: '2026-10-01T18:00:00Z',
    balance_cents: 0,
    last_topup_at: null,
  },
]

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) =>
      path.startsWith('/api/kassa/wallets?')
        ? json(200, FOUND)
        : json(201, { entry_id: 20, wallet_id: 9, amount_cents: 1500, created_at: 'x' }),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function show(onMoved = vi.fn(), onClose = vi.fn()) {
  render(<MoveDialog target={OPEN} onMoved={onMoved} onClose={onClose} />)
  return { onMoved, onClose }
}

async function search(text = 'jan') {
  fireEvent.change(screen.getByLabelText('Naam of code van de oude wallet'), {
    target: { value: text },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Zoeken' }))
  await act(async () => {})
}

const matches = () =>
  within(screen.getByRole('list', { name: 'Gevonden wallets' })).getAllByRole('button')

describe('MoveDialog', () => {
  it('searches by name and never offers the open wallet (AC25)', async () => {
    show()
    await search('jan')
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/kassa/wallets?name=jan')
    expect(matches().map((row) => row.querySelector('strong')?.textContent)).toEqual([
      'Jan',
      'Janneke',
    ])
  })

  it('shows each match with its name, sign-up date, balance and last top-up (AC25)', async () => {
    show()
    await search()
    const [jan, janneke] = matches()
    expect(jan.textContent).toContain('Jan')
    expect(jan.textContent).toContain(
      `aangemaakt ${formatDayMonth(Date.parse(FOUND[0].created_at))}`,
    )
    expect(jan.textContent).toContain(formatEuro(1500))
    expect(jan.textContent).toContain(
      `opgewaardeerd ${formatDayMonthTime(Date.parse(FOUND[0].last_topup_at as string))}`,
    )
    expect(janneke.textContent).toContain('nog niet opgewaardeerd')
  })

  it('confirms with both names and posts the move (AC26)', async () => {
    const { onMoved } = show()
    await search()
    fireEvent.click(matches()[0])
    expect(screen.getByRole('dialog').textContent).toContain(
      `${formatEuro(1500)} en de naam 'Jan' van Jan (aangemaakt ` +
        `${formatDayMonth(Date.parse(FOUND[0].created_at))}) naar Jan 2 overzetten?`,
    )
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Overzetten' }))
    await act(async () => {})

    const [path, init] = vi.mocked(fetch).mock.calls[1]
    expect(path).toBe('/api/kassa/wallets/9/move')
    expect(JSON.parse(String(init?.body))).toEqual({ from_wallet_id: 4 })
    expect((init?.headers as Record<string, string>)['Idempotency-Key']).toMatch(/^[0-9a-f]{32}$/)
    expect(onMoved).toHaveBeenCalledTimes(1)
  })

  it('a 409 nothing_to_move says so (AC27)', async () => {
    const { onMoved } = show()
    await search()
    vi.mocked(fetch).mockResolvedValueOnce(
      json(409, { error: { code: 'nothing_to_move', message: 'no' } }),
    )
    fireEvent.click(matches()[1])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Overzetten' }))
    await act(async () => {})
    expect(screen.getByRole('alert').textContent).toBe('Er is niets over te zetten.')
    expect(onMoved).not.toHaveBeenCalled()
  })

  it('cancelling the confirm sends nothing, and "Annuleren" closes', async () => {
    const { onClose } = show()
    await search()
    fireEvent.click(matches()[0])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(vi.mocked(fetch).mock.calls).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('no other wallet found says so', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(200, [FOUND[1]]))
    show()
    await search()
    expect(screen.getByText('Geen andere wallet gevonden')).toBeTruthy()
  })
})

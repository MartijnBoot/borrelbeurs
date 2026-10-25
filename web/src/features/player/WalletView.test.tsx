// @vitest-environment jsdom
// The player's wallet (B-05 SD21; AC9, AC29).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatBalance, formatEuro } from '../../lib/format'
import { WalletView } from './WalletView'

const WALLET = {
  name: 'Jan',
  balance_cents: 3500,
  qr_token: 'tok-1',
  short_code: 'K7Q4-M2XD',
  created_at: '2026-10-25T10:00:00Z',
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(null, { status: 204 })),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function show(onDeleted = vi.fn(), balance = WALLET.balance_cents) {
  const view = render(
    <WalletView wallet={{ ...WALLET, balance_cents: balance }} onDeleted={onDeleted} />,
  )
  return { onDeleted, view }
}

function confirmDelete() {
  fireEvent.click(screen.getByRole('button', { name: 'Wallet verwijderen' }))
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Wallet verwijderen' }),
  )
}

describe('WalletView (AC9)', () => {
  it('shows the name, balance, QR code, short code, delete and the hint, and nothing else', () => {
    const { view } = show()
    expect(screen.getByRole('heading', { name: 'Jan' })).toBeTruthy()
    expect(screen.getByRole('img', { name: 'QR-code' })).toBeTruthy()
    const texts = Array.from(view.container.querySelectorAll('h1, p, button')).map(
      (node) => node.textContent,
    )
    expect(texts).toEqual([
      'Jan',
      formatEuro(3500),
      'K7Q4-M2XD',
      'Bewaar deze pagina — je wallet staat op deze telefoon.',
      'Wallet verwijderen',
    ])
    expect(view.container.textContent).toBe(texts.join(''))
  })

  it('shows a debt with its minus sign (B-06 SD19, AC25)', () => {
    const { view } = show(vi.fn(), -210)
    const texts = Array.from(view.container.querySelectorAll('h1, p, button')).map(
      (node) => node.textContent,
    )
    expect(texts[1]).toBe(formatBalance(-210))
    expect(texts[1]?.startsWith('\u2212')).toBe(true)
  })
})

describe('deleting a wallet in debt (B-06 SD8, AC26, PD19)', () => {
  it('says to top up first and sends nothing', () => {
    const { onDeleted } = show(vi.fn(), -210)
    fireEvent.click(screen.getByRole('button', { name: 'Wallet verwijderen' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('alert').textContent).toBe('Eerst aanvullen bij de kassa')
    expect(fetch).not.toHaveBeenCalled()
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('at exactly zero the confirm opens as before', () => {
    show(vi.fn(), 0)
    fireEvent.click(screen.getByRole('button', { name: 'Wallet verwijderen' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      `Je saldo van ${formatEuro(0)} vervalt.`,
    )
  })

  it('a 409 balance_negative (the balance fell meanwhile) shows the same text', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: 'balance_negative', message: 'debt' } }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const { onDeleted } = show()
    confirmDelete()
    await act(async () => {})
    expect(onDeleted).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toBe('Eerst aanvullen bij de kassa')
  })
})

describe('deleting (AC29)', () => {
  it('asks first, with the balance that is lost', () => {
    show()
    fireEvent.click(screen.getByRole('button', { name: 'Wallet verwijderen' }))
    const dialog = screen.getByRole('dialog')
    // textContent, not getByText: its normalizer folds formatEuro's no-break space.
    expect(dialog.textContent).toContain(`Je saldo van ${formatEuro(3500)} vervalt.`)
  })

  it('cancel sends nothing', () => {
    const { onDeleted } = show()
    fireEvent.click(screen.getByRole('button', { name: 'Wallet verwijderen' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(fetch).not.toHaveBeenCalled()
    expect(onDeleted).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('confirm sends DELETE /api/wallet, then sign-up', async () => {
    const { onDeleted } = show()
    confirmDelete()
    await act(async () => {})
    expect(vi.mocked(fetch).mock.calls).toEqual([
      ['/api/wallet', expect.objectContaining({ method: 'DELETE' })],
    ])
    expect(onDeleted).toHaveBeenCalledTimes(1)
  })

  it('a network failure keeps the wallet and says so', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    const { onDeleted } = show()
    confirmDelete()
    await act(async () => {})
    expect(onDeleted).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
  })
})

// @vitest-environment jsdom
// Top up (B-05 SD10; AC15-AC18).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatEuro } from '../../lib/format'
import { formatHourMinute } from '../../lib/time'
import type { KassaWallet } from './api'
import { TopUpPanel } from './TopUpPanel'

const WALLET: KassaWallet = {
  wallet_id: 7,
  name: 'Jan',
  balance_cents: 0,
  created_at: '2026-10-25T18:00:00Z',
  last_topup_at: null,
  recent_topup: null,
}

const BOOKED = { entry_id: 1, wallet_id: 7, amount_cents: 1500, created_at: '2026-10-25T20:00:00Z' }

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(BOOKED), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function show(wallet: KassaWallet = WALLET, onBooked = vi.fn()) {
  render(<TopUpPanel wallet={wallet} onBooked={onBooked} />)
  return onBooked
}

const minus = () => screen.getByRole('button', { name: '€ 5 minder' }) as HTMLButtonElement
const plus = () => screen.getByRole('button', { name: '€ 5 meer' }) as HTMLButtonElement
const amount = () => screen.getByLabelText('Bedrag').textContent
const dialog = () => screen.getByRole('dialog')
const sent = () =>
  vi.mocked(fetch).mock.calls.map(([path, init]) => ({
    path,
    method: init?.method,
    body: JSON.parse(String(init?.body)),
    key: (init?.headers as Record<string, string>)['Idempotency-Key'],
  }))

async function confirm(label = 'Opwaarderen') {
  fireEvent.click(within(dialog()).getByRole('button', { name: label }))
  await act(async () => {})
}

describe('the steps (AC16)', () => {
  it('start at €10 with [−] disabled, and reach €100 in nineteen [+]', () => {
    show()
    expect(amount()).toBe(formatEuro(1000))
    expect(minus().disabled).toBe(true)
    for (let step = 0; step < 19; step++) fireEvent.click(plus())
    expect(amount()).toBe(formatEuro(10_000))
    expect(plus().disabled).toBe(true)
    fireEvent.click(minus())
    expect(amount()).toBe(formatEuro(9_500))
    expect(plus().disabled).toBe(false)
  })
})

describe('the confirm (AC15, AC17)', () => {
  it('asks "<€X> opwaarderen voor <naam>?" and posts the amount with a key', async () => {
    const onBooked = show()
    fireEvent.click(plus())
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    expect(dialog().textContent).toContain(`${formatEuro(1500)} opwaarderen voor Jan?`)

    await confirm()

    const [request] = sent()
    expect(request).toMatchObject({
      path: '/api/kassa/wallets/7/topups',
      method: 'POST',
      body: { amount_cents: 1500 },
    })
    expect(request.key).toMatch(/^[0-9a-f]{32}$/)
    expect(onBooked).toHaveBeenCalledTimes(1)
  })

  it('after a top-up in the last 2 minutes, asks again with the earlier one (AC17)', async () => {
    const at = '2026-10-25T19:58:30Z'
    show({ ...WALLET, recent_topup: { at, amount_cents: 2000 } })
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    expect(dialog().textContent).toContain(
      `Jan is om ${formatHourMinute(Date.parse(at))} al opgewaardeerd met ${formatEuro(2000)}.` +
        ` Nog een keer ${formatEuro(1000)}?`,
    )
    await confirm('Ja, nog een keer')
    expect(sent()).toHaveLength(1)
  })

  it('cancel sends nothing', () => {
    const onBooked = show()
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Annuleren' }))
    expect(fetch).not.toHaveBeenCalled()
    expect(onBooked).not.toHaveBeenCalled()
  })

  it('two confirmed top-ups carry two keys', async () => {
    show()
    for (let n = 0; n < 2; n++) {
      fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
      await confirm()
    }
    const [first, second] = sent()
    expect(first.key).not.toBe(second.key)
  })
})

describe('a retry (AC18)', () => {
  it('after a network failure, "Opnieuw" resends the same intent under the same key', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    const onBooked = show()
    fireEvent.click(plus())
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    await confirm()
    expect(screen.getByRole('alert').textContent).toContain('Verbindingsfout. Probeer opnieuw.')
    expect(onBooked).not.toHaveBeenCalled()

    fireEvent.click(plus()) // the stepper moving on does not change the intent being retried
    fireEvent.click(screen.getByRole('button', { name: 'Opnieuw' }))
    await act(async () => {})

    const [failed, retried] = sent()
    expect(retried.key).toBe(failed.key)
    expect(retried.body).toEqual({ amount_cents: 1500 })
    expect(onBooked).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

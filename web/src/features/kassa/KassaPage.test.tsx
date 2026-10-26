// @vitest-environment jsdom
// The kassa page (B-05 SD22; AC14, AC15): a typed code, the found wallet, a top-up.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatBalance, formatEuro } from '../../lib/format'
import { KassaPage } from './KassaPage'

vi.mock('../../components/scanner/decodeQr', () => ({ decode: vi.fn(async () => 'tok-scanned') }))

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

const PAYMENTS = [
  {
    entry_id: 9,
    amount_cents: 840,
    created_at: '2026-10-25T21:00:00Z',
    lines: [{ name: 'Bier', qty: 2 }],
    refunded: false,
    actor_label: 'Bar 1',
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
      if (path === '/api/kassa/wallets/7/payments') return json(200, PAYMENTS)
      if (path === '/api/payments/9/refund' && init?.method === 'POST') {
        balance += 840
        return json(201, { entry_id: 10, wallet_id: 7, amount_cents: 840, created_at: 'x' })
      }
      if (path === '/api/kassa/wallets/7/new-code') {
        return json(200, { qr_token: 'tok-new', short_code: 'AAAA-BBBB' })
      }
      throw new Error(`unexpected ${path}`)
    }),
  )
})

const secure = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
const devices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')

function setContext(isSecure: boolean, getUserMedia?: () => Promise<MediaStream>) {
  Object.defineProperty(window, 'isSecureContext', { value: isSecure, configurable: true })
  Object.defineProperty(navigator, 'mediaDevices', {
    value: getUserMedia === undefined ? undefined : { getUserMedia },
    configurable: true,
  })
}

/** A camera whose every frame decodes to `tok-scanned` (the `decodeQr` mock). */
function fakeCamera() {
  const stopTrack = vi.fn()
  setContext(
    true,
    async () => ({ getTracks: () => [{ stop: stopTrack }] }) as unknown as MediaStream,
  )
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLVideoElement.prototype, 'videoWidth', 'get').mockReturnValue(64)
  vi.spyOn(HTMLVideoElement.prototype, 'videoHeight', 'get').mockReturnValue(64)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: () => {},
    getImageData: (_x: number, _y: number, width: number, height: number) => ({
      data: new Uint8ClampedArray(width * height * 4),
      width,
      height,
    }),
  } as unknown as CanvasRenderingContext2D)
  return stopTrack
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  if (secure) Object.defineProperty(window, 'isSecureContext', secure)
  else delete (window as { isSecureContext?: boolean }).isSecureContext
  if (devices) Object.defineProperty(navigator, 'mediaDevices', devices)
  else delete (navigator as { mediaDevices?: unknown }).mediaDevices
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

  it("shows the wallet's payments under its top-ups; a refund looks it up again (B-06 AC23)", async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    const [row] = within(screen.getByRole('list', { name: 'Betalingen' })).getAllByRole('listitem')
    expect(row.textContent).toContain(`2× Bier — ${formatEuro(840)}`)
    fireEvent.click(within(row).getByRole('button', { name: 'Terugboeken' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Terugboeken' }))
    await act(async () => {})
    expect(lookups()).toHaveLength(2)
    expect(screen.getByRole('region', { name: 'Jan' }).textContent).toContain(formatEuro(2340))
  })

  it('shows a debt with its minus sign (B-06 SD19, AC25)', async () => {
    balance = -210
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    const card = screen.getByRole('region', { name: 'Jan' })
    expect(card.textContent).toContain(formatBalance(-210))
    expect(card.textContent).toContain('\u2212€')
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
    await act(async () => {})
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Opwaarderen' }))
    await act(async () => {})
    // Found, again before the confirm (/review R2), and again after the booking.
    expect(lookups()).toHaveLength(3)
    expect(screen.getByRole('region', { name: 'Jan' }).textContent).toContain(formatEuro(2500))
  })

  it('the lookup before the confirm shows the balance as it is now (/review R2)', async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    balance = 4500 // another kassa booked meanwhile
    fireEvent.click(screen.getByRole('button', { name: 'Opwaarderen' }))
    await act(async () => {})
    expect(screen.getByRole('region', { name: 'Jan' }).textContent).toContain(formatEuro(4500))
  })

  it('a lookup that answers after a later one is dropped (/review R2)', async () => {
    let answerJan: (response: Response) => void = () => {}
    const PIET = { ...JAN, wallet_id: 8, name: 'Piet' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        if (path === '/api/kassa/lookup') {
          const body = JSON.parse(String(init?.body))
          if (body.qr_token === 'tok-scanned') return json(200, PIET)
          return new Promise<Response>((resolve) => {
            answerJan = resolve
          })
        }
        if (/^\/api\/kassa\/wallets\/[78]\/(topups|payments)$/.test(path)) return json(200, [])
        throw new Error(`unexpected ${path}`)
      }),
    )
    fakeCamera()
    render(<KassaPage />)
    // The camera is open while a typed code is still being looked up; it finds Piet first.
    fireEvent.click(screen.getByRole('button', { name: 'Camera' }))
    await find('K7Q4-M2XD')
    await act(() => new Promise((resolve) => setTimeout(resolve, 300)))
    expect(screen.getByRole('region', { name: 'Piet' })).toBeTruthy()

    await act(async () => answerJan(json(200, JAN)))

    expect(screen.queryByRole('region', { name: 'Jan' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Piet' })).toBeTruthy()
  })

  it('"Nieuwe code" asks first, then shows the new code and looks up by it (AC28)', async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe code' }))
    expect(screen.getByRole('dialog').textContent).toContain(
      'Nieuwe code maken voor Jan? De oude QR-code en code werken dan niet meer.',
    )
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Nieuwe code' }))
    await act(async () => {})

    expect(
      vi.mocked(fetch).mock.calls.some(([path]) => path === '/api/kassa/wallets/7/new-code'),
    ).toBe(true)
    expect(screen.getByText('AAAA-BBBB')).toBeTruthy()
    expect(lookups().at(-1)).toEqual({ short_code: 'AAAA-BBBB' })
  })

  it('"Nieuwe code" cancelled sends nothing', async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    const before = vi.mocked(fetch).mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Nieuwe code' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Annuleren' }))
    expect(vi.mocked(fetch).mock.calls).toHaveLength(before)
  })

  it('"Saldo overzetten van…" opens the move search', async () => {
    render(<KassaPage />)
    await find('K7Q4-M2XD')
    fireEvent.click(screen.getByRole('button', { name: 'Saldo overzetten van…' }))
    expect(screen.getByRole('region', { name: 'Saldo overzetten' })).toBeTruthy()
  })

  it('an empty field asks nothing', async () => {
    render(<KassaPage />)
    await find('   ')
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('the camera (AC14, AC42)', () => {
  it('is not offered outside a secure context, and nothing says why', () => {
    setContext(false, async () => ({}) as MediaStream)
    render(<KassaPage />)
    expect(screen.queryByRole('button', { name: 'Camera' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
  })

  it('is offered beside "Code typen" in a secure context', () => {
    setContext(true, async () => ({}) as MediaStream)
    render(<KassaPage />)
    expect(screen.getByRole('button', { name: 'Camera' })).toBeTruthy()
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
  })

  it('a refused camera says so and leaves the code field', async () => {
    setContext(true, () => Promise.reject(new DOMException('denied', 'NotAllowedError')))
    render(<KassaPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Camera' }))
    await act(async () => {})
    expect(screen.getByRole('alert').textContent).toBe('Geen toegang tot de camera.')
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
  })

  it('a scanned token is looked up as qr_token, and every track is stopped', async () => {
    const stopTrack = fakeCamera()

    render(<KassaPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Camera' }))
    await act(() => new Promise((resolve) => setTimeout(resolve, 300)))

    expect(lookups()).toEqual([{ qr_token: 'tok-scanned' }])
    expect(stopTrack).toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: 'Camera' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Jan' })).toBeTruthy()
  })
})

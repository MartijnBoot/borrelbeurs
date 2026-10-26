// @vitest-environment jsdom
// The bar's wallet picker (B-06 T13: SD12, SD13; AC4, AC32; PD18): a typed code or,
// where the browser allows a camera, a scanned QR, looked up as the bar may see it.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HeldWallet } from './model/barController'
import { WalletPicker } from './WalletPicker'

vi.mock('../../components/scanner/decodeQr', () => ({ decode: vi.fn(async () => 'tok-scanned') }))

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let answer: (body: Record<string, string>) => Promise<Response>
let found: HeldWallet[]

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
  setContext(
    true,
    async () => ({ getTracks: () => [{ stop: () => {} }] }) as unknown as MediaStream,
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
}

beforeEach(() => {
  found = []
  answer = async () => json(200, { name: 'Jan', balance_cents: -90 })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path !== '/api/bar/wallet-lookup') throw new Error(`unexpected ${path}`)
      return answer(JSON.parse(String(init?.body)))
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  if (secure) Object.defineProperty(window, 'isSecureContext', secure)
  else delete (window as { isSecureContext?: boolean }).isSecureContext
  if (devices) Object.defineProperty(navigator, 'mediaDevices', devices)
  else delete (navigator as { mediaDevices?: unknown }).mediaDevices
})

function open() {
  render(<WalletPicker disabled={false} onFound={(wallet) => found.push(wallet)} />)
}

async function typeAndSearch(code: string) {
  fireEvent.change(screen.getByLabelText('Code typen'), { target: { value: code } })
  fireEvent.click(screen.getByRole('button', { name: 'Zoeken' }))
  await act(async () => {})
}

const sent = () => vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
const typed = () => (screen.getByLabelText('Code typen') as HTMLInputElement).value

describe('WalletPicker', () => {
  it('sends the typed code as typed and holds the wallet it names (AC4)', async () => {
    setContext(false)
    open()
    await typeAndSearch(' k7mq-x2p9 ')
    expect(sent()).toEqual([{ short_code: ' k7mq-x2p9 ' }])
    expect(found).toEqual([
      { query: { short_code: ' k7mq-x2p9 ' }, name: 'Jan', balance_cents: -90 },
    ])
  })

  it('a 404 says "Onbekende wallet", holds nothing and keeps the code (AC4)', async () => {
    setContext(false)
    answer = async () => json(404, { error: { code: 'wallet_not_found', message: 'no' } })
    open()
    await typeAndSearch('ZZZZ-ZZZZ')
    expect(screen.getByRole('alert').textContent).toBe('Onbekende wallet')
    expect(found).toEqual([])
    expect(typed()).toBe('ZZZZ-ZZZZ')
  })

  it.each([
    ['a network failure', async () => Promise.reject(new TypeError('Failed to fetch'))],
    [
      'a 503 shutting_down',
      async () => json(503, { error: { code: 'shutting_down', message: 'no' } }),
    ],
    ['a 503 standby', async () => json(503, { error: { code: 'standby', message: 'no' } })],
  ])(
    '%s says "Verbindingsfout. Probeer opnieuw.", holds nothing and keeps the code (PD18)',
    async (_, fails) => {
      setContext(false)
      answer = fails
      open()
      await typeAndSearch('K7MQ-X2P9')
      expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
      expect(found).toEqual([])
      expect(typed()).toBe('K7MQ-X2P9')
    },
  )

  it('offers no "Camera" and shows no error where the browser allows none (AC32)', () => {
    setContext(false)
    open()
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Camera' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('offers both where it does; a scan sends the token (AC32)', async () => {
    fakeCamera()
    open()
    expect(screen.getByLabelText('Code typen')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Camera' }))
    await act(async () => {})
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250))
    })
    expect(sent()).toEqual([{ qr_token: 'tok-scanned' }])
    expect(found).toEqual([{ query: { qr_token: 'tok-scanned' }, name: 'Jan', balance_cents: -90 }])
  })

  it('is disabled while the basket is locked', () => {
    setContext(false)
    render(<WalletPicker disabled onFound={() => {}} />)
    expect((screen.getByRole('button', { name: 'Zoeken' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
  })
})

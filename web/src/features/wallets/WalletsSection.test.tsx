// @vitest-environment jsdom
// The Wallets section (B-05 SD6, SD15, SD16; AC30, AC33, AC34; PD2, PD12, PD20).
// B-06 SD20, PD10, PD18: "Tegoed" and "Rood", payments per borrel, debt (AC25, AC30).
// B-09: the confirm before printed codes break, the QR preview and its downloads.
// B-10: the switch for the sign-up QR code on the koers screen (AC10).
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import jsQR from 'jsqr'
import { encode } from 'uqr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pngBlob, saveFile, svgDocument } from '../../components/qr/qrFiles'
import { formatBalance, formatEuro } from '../../lib/format'
import { formatDayMonth } from '../../lib/time'
import { SIGNUP_QR, signupLink } from './signupQr'
import { WalletsSection } from './WalletsSection'

// jsdom's own address is http://localhost:3000, a loopback host (PD8): a test that needs the
// buttons enabled sets `address`; null keeps the page's real one.
const page = vi.hoisted(() => ({
  address: null as { origin: string; host: string; hostname: string } | null,
}))
vi.mock('./signupQr', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./signupQr')>()
  return { ...actual, pageAddress: () => page.address ?? actual.pageAddress() }
})
vi.mock('../../components/qr/qrFiles', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../components/qr/qrFiles')>()),
  pngBlob: vi.fn(),
  saveFile: vi.fn(),
}))

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
const STORED = {
  signup_code: 'Borrel2026',
  unfunded_days: 30,
  inactive_months: 12,
  show_signup_on_screen: false,
}

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let overview: typeof OVERVIEW
let stored:
  | typeof STORED
  | {
      signup_code: null
      unfunded_days: number
      inactive_months: number
      show_signup_on_screen: boolean
    }
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
    await click(screen.getByRole('dialog'), 'Wijzigen')
    expect(puts()).toEqual([
      {
        signup_code: 'Nieuw',
        unfunded_days: 30,
        inactive_months: 12,
        show_signup_on_screen: false,
      },
    ])
    expect(within(code).getByText(`${window.location.origin}/speler?code=Nieuw`)).toBeTruthy()
  })

  it('"Wissen" sends null and says sign-up is closed (AC34)', async () => {
    await open()
    const code = region('Aanmeldcode')
    await click(code, 'Wissen')
    await click(screen.getByRole('dialog'), 'Wissen')
    expect(puts()).toEqual([
      { signup_code: null, unfunded_days: 30, inactive_months: 12, show_signup_on_screen: false },
    ])
    expect(within(code).getByText('Aanmelden is gesloten.')).toBeTruthy()
    expect((within(code).getByLabelText('Aanmeldcode') as HTMLInputElement).value).toBe('')
  })

  it('no code set says sign-up is closed', async () => {
    stored = {
      signup_code: null,
      unfunded_days: 30,
      inactive_months: 12,
      show_signup_on_screen: false,
    }
    await open()
    expect(within(region('Aanmeldcode')).getByText('Aanmelden is gesloten.')).toBeTruthy()
  })
})

describe('Confirm before printed codes break (B-09 SD7, SD9)', () => {
  const CHANGE = "Aanmeldcode wijzigen? Geprinte QR-codes met 'Borrel2026' werken dan niet meer."
  const CLEAR = "Aanmelden sluiten? Geprinte QR-codes met 'Borrel2026' werken dan niet meer."

  const field = () =>
    within(region('Aanmeldcode')).getByLabelText('Aanmeldcode') as HTMLInputElement
  const type = (value: string) => fireEvent.change(field(), { target: { value } })
  const dialogButtons = () =>
    within(screen.getByRole('dialog'))
      .getAllByRole('button')
      .map((button) => button.textContent)

  it('a different code asks first, and "Wijzigen" saves it once (AC11)', async () => {
    await open()
    type('Anders')
    await click(region('Aanmeldcode'), 'Opslaan')
    expect(screen.getByRole('dialog').textContent).toContain(CHANGE)
    expect(dialogButtons()).toEqual(['Wijzigen', 'Annuleren'])
    expect(puts()).toEqual([])

    await click(screen.getByRole('dialog'), 'Wijzigen')
    expect(puts()).toEqual([
      {
        signup_code: 'Anders',
        unfunded_days: 30,
        inactive_months: 12,
        show_signup_on_screen: false,
      },
    ])
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('"Wissen" asks to close sign-up, and its "Wissen" sends null (AC12)', async () => {
    await open()
    await click(region('Aanmeldcode'), 'Wissen')
    expect(screen.getByRole('dialog').textContent).toContain(CLEAR)
    expect(dialogButtons()).toEqual(['Wissen', 'Annuleren'])
    expect(puts()).toEqual([])

    await click(screen.getByRole('dialog'), 'Wissen')
    expect(puts()).toEqual([
      { signup_code: null, unfunded_days: 30, inactive_months: 12, show_signup_on_screen: false },
    ])
    expect(within(region('Aanmeldcode')).getByText('Aanmelden is gesloten.')).toBeTruthy()
  })

  it('"Opslaan" over a whitespace-only field asks to close sign-up too (AC12)', async () => {
    await open()
    type('   ')
    await click(region('Aanmeldcode'), 'Opslaan')
    expect(screen.getByRole('dialog').textContent).toContain(CLEAR)
    expect(puts()).toEqual([])

    await click(screen.getByRole('dialog'), 'Wissen')
    expect(puts()).toEqual([
      { signup_code: '   ', unfunded_days: 30, inactive_months: 12, show_signup_on_screen: false },
    ])
    expect(within(region('Aanmeldcode')).getByText('Aanmelden is gesloten.')).toBeTruthy()
  })

  it.each([
    ['a change', 'Anders', 'Opslaan'],
    ['a clear', 'Getypt', 'Wissen'],
  ])(
    '"Annuleren" after %s saves nothing and keeps the typed text (AC13)',
    async (_, typed, button) => {
      await open()
      type(typed)
      await click(region('Aanmeldcode'), button)
      await click(screen.getByRole('dialog'), 'Annuleren')

      expect(puts()).toEqual([])
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(field().value).toBe(typed)
      const code = region('Aanmeldcode')
      expect(
        within(code).getByText(`${window.location.origin}/speler?code=Borrel2026`),
      ).toBeTruthy()
      expect(within(code).queryByText('Aanmelden is gesloten.')).toBeNull()
    },
  )

  it.each([
    ['a case-only change', 'BORREL', 'borrel', 'Opslaan'],
    ['the same code with spaces', 'BORREL', ' BORREL ', 'Opslaan'],
    ['a first code', null, 'Nieuw', 'Opslaan'],
    ['"Wissen" with none saved', null, '', 'Wissen'],
  ])('%s saves at once with no dialog (AC14)', async (_, saved, typed, button) => {
    stored = {
      signup_code: saved as never,
      unfunded_days: 30,
      inactive_months: 12,
      show_signup_on_screen: false,
    }
    await open()
    type(typed)
    await click(region('Aanmeldcode'), button)

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(puts()).toEqual([
      {
        signup_code: button === 'Wissen' ? null : typed,
        unfunded_days: 30,
        inactive_months: 12,
        show_signup_on_screen: false,
      },
    ])
  })
})

describe('The QR preview and its downloads (B-09 SD1–SD6, SD8, SD10)', () => {
  const LAN = { origin: 'http://192.168.8.10', host: '192.168.8.10', hostname: '192.168.8.10' }
  const LOOPBACK = {
    origin: 'http://localhost:3000',
    host: 'localhost:3000',
    hostname: 'localhost',
  }
  const HINT =
    'Open deze pagina via het netwerkadres (bijv. http://192.168.8.10/) om de QR-code te downloaden.'

  beforeEach(() => {
    page.address = LAN
    vi.mocked(pngBlob).mockReset()
    vi.mocked(saveFile).mockReset()
  })
  afterEach(() => {
    page.address = null
  })

  const preview = () =>
    within(region('Aanmeldcode')).queryByRole('img', { name: 'Aanmeld-QR-code' })
  const button = (name: string) =>
    within(region('Aanmeldcode')).queryByRole('button', { name }) as HTMLButtonElement | null
  const cells = (svg: Element) =>
    Array.from(svg.querySelectorAll('rect'), (r) => `${r.getAttribute('x')},${r.getAttribute('y')}`)
  const expectedCells = (code: string) =>
    encode(signupLink(LAN.origin, code), SIGNUP_QR).data.flatMap((row, y) =>
      row.flatMap((dark, x) => (dark ? [`${x},${y}`] : [])),
    )

  // The preview rendered to pixels, as a camera would see it, then read with jsqr.
  function readPreview(svg: Element, k = 6) {
    const [, , n] = svg.getAttribute('viewBox')!.split(' ').map(Number)
    const width = n * k
    const data = new Uint8ClampedArray(width * width * 4).fill(255)
    for (const rect of Array.from(svg.querySelectorAll('rect'))) {
      const [x, y] = [Number(rect.getAttribute('x')), Number(rect.getAttribute('y'))]
      for (let py = y * k; py < (y + 1) * k; py++) {
        for (let px = x * k; px < (x + 1) * k; px++)
          data.fill(0, (py * width + px) * 4, (py * width + px) * 4 + 3)
      }
    }
    return jsQR(data, width, width, { inversionAttempts: 'dontInvert' })?.data
  }

  it('a saved code shows the link, the preview and both buttons, enabled (AC1)', async () => {
    await open()
    expect(
      within(region('Aanmeldcode')).getByText(`${LAN.origin}/speler?code=Borrel2026`),
    ).toBeTruthy()
    expect(preview()).not.toBeNull()
    expect(button('Download PNG')?.disabled).toBe(false)
    expect(button('Download SVG')?.disabled).toBe(false)
  })

  it('no code saved: closed, no preview and no buttons (AC2)', async () => {
    stored = {
      signup_code: null,
      unfunded_days: 30,
      inactive_months: 12,
      show_signup_on_screen: false,
    }
    await open()
    expect(within(region('Aanmeldcode')).getByText('Aanmelden is gesloten.')).toBeTruthy()
    expect(preview()).toBeNull()
    expect(button('Download PNG')).toBeNull()
    expect(button('Download SVG')).toBeNull()
  })

  it('typing does not change the preview; the save does, to the code the server returns (AC3)', async () => {
    await open()
    expect(cells(preview()!)).toEqual(expectedCells('Borrel2026'))

    fireEvent.change(within(region('Aanmeldcode')).getByLabelText('Aanmeldcode'), {
      target: { value: '  Nieuw  ' },
    })
    expect(cells(preview()!)).toEqual(expectedCells('Borrel2026'))

    await click(region('Aanmeldcode'), 'Opslaan')
    await click(screen.getByRole('dialog'), 'Wijzigen')
    expect(cells(preview()!)).toEqual(expectedCells('Nieuw'))
  })

  it.each(['Borrel2026', 'a b&c#é'])(
    'the preview decodes to the link shown for %j (AC4)',
    async (code) => {
      stored = { ...STORED, signup_code: code }
      await open()
      const link = `${LAN.origin}/speler?code=${encodeURIComponent(code)}`
      expect(within(region('Aanmeldcode')).getByText(link)).toBeTruthy()
      expect(readPreview(preview()!)).toBe(link)
    },
  )

  it('the preview draws Q with a 4-module quiet zone (AC5)', async () => {
    await open()
    const modules = encode(signupLink(LAN.origin, 'Borrel2026'), SIGNUP_QR).data
    expect(preview()!.getAttribute('viewBox')).toBe(`0 0 ${modules.length} ${modules.length}`)
    expect(cells(preview()!)).toEqual(expectedCells('Borrel2026'))
  })

  it('"Download PNG" saves the PNG of the same modules under the SD8 name', async () => {
    const png = new Blob(['png'], { type: 'image/png' })
    vi.mocked(pngBlob).mockResolvedValue(png)
    await open()
    await click(region('Aanmeldcode'), 'Download PNG')

    expect(vi.mocked(pngBlob).mock.calls[0][0]).toEqual(
      encode(signupLink(LAN.origin, 'Borrel2026'), SIGNUP_QR).data,
    )
    expect(vi.mocked(saveFile).mock.calls).toEqual([[png, 'aanmelden-192.168.8.10-Borrel2026.png']])
  })

  it('"Download SVG" saves the SVG document under the SD8 name', async () => {
    await open()
    await click(region('Aanmeldcode'), 'Download SVG')

    const [[blob, name]] = vi.mocked(saveFile).mock.calls
    expect(name).toBe('aanmelden-192.168.8.10-Borrel2026.svg')
    expect(blob.type).toBe('image/svg+xml')
    expect(await blob.text()).toBe(
      svgDocument(encode(signupLink(LAN.origin, 'Borrel2026'), SIGNUP_QR).data),
    )
  })

  it('a PNG that cannot be made says so and throws nothing (PD9)', async () => {
    vi.mocked(pngBlob).mockRejectedValue(new Error('no 2d canvas'))
    await open()
    await click(region('Aanmeldcode'), 'Download PNG')

    expect(within(region('Aanmeldcode')).getByRole('alert').textContent).toBe(
      'Downloaden lukt niet. Probeer opnieuw.',
    )
    expect(saveFile).not.toHaveBeenCalled()
  })

  it('at a loopback host the buttons are disabled and the hint shows, with the preview (AC10)', async () => {
    page.address = LOOPBACK
    await open()
    expect(preview()).not.toBeNull()
    expect(button('Download PNG')?.disabled).toBe(true)
    expect(button('Download SVG')?.disabled).toBe(true)
    expect(within(region('Aanmeldcode')).getByText(HINT)).toBeTruthy()
  })

  it('at a LAN host there is no hint (AC10)', async () => {
    await open()
    expect(within(region('Aanmeldcode')).queryByText(HINT)).toBeNull()
  })
})

describe('Bewaartermijnen (AC33)', () => {
  it('sends both periods as numbers', async () => {
    await open()
    const periods = region('Bewaartermijnen')
    fireEvent.change(within(periods).getByLabelText(/dagen/), { target: { value: '7' } })
    fireEvent.change(within(periods).getByLabelText(/maanden/), { target: { value: '3' } })
    await click(periods, 'Opslaan')
    expect(puts()).toEqual([
      {
        signup_code: 'Borrel2026',
        unfunded_days: 7,
        inactive_months: 3,
        show_signup_on_screen: false,
      },
    ])
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

describe('"QR-code op het scherm" (B-10 SD5; AC10)', () => {
  const box = () =>
    within(region('Aanmeldcode')).getByRole('checkbox', {
      name: 'QR-code op het scherm',
    }) as HTMLInputElement

  async function toggle() {
    fireEvent.click(box())
    await act(async () => {})
  }

  it('shows the stored switch', async () => {
    await open()
    expect(box().checked).toBe(false)
    cleanup()

    stored = { ...STORED, show_signup_on_screen: true }
    await open()
    expect(box().checked).toBe(true)
  })

  it('toggling sends one PUT with the switch flipped and the rest as stored, and asks nothing', async () => {
    await open()
    // Unsaved text in the code field is not sent with the switch.
    fireEvent.change(within(region('Aanmeldcode')).getByLabelText('Aanmeldcode'), {
      target: { value: 'Getypt' },
    })
    await toggle()

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(puts()).toEqual([{ ...STORED, show_signup_on_screen: true }])
    expect(box().checked).toBe(true)

    await toggle()
    expect(puts()).toEqual([
      { ...STORED, show_signup_on_screen: true },
      { ...STORED, show_signup_on_screen: false },
    ])
    expect(box().checked).toBe(false)
  })

  it('changing the code still asks first, and keeps the switch as stored', async () => {
    stored = { ...STORED, show_signup_on_screen: true }
    await open()
    fireEvent.change(within(region('Aanmeldcode')).getByLabelText('Aanmeldcode'), {
      target: { value: 'Anders' },
    })
    await click(region('Aanmeldcode'), 'Opslaan')
    expect(screen.getByRole('dialog')).toBeTruthy()
    await click(screen.getByRole('dialog'), 'Wijzigen')

    expect(puts()).toEqual([{ ...STORED, signup_code: 'Anders', show_signup_on_screen: true }])
  })

  it('a failed save says so and leaves the box as stored', async () => {
    await open()
    putAnswer = () => {
      throw new TypeError('offline')
    }
    await toggle()

    expect(within(region('Aanmeldcode')).getByRole('alert').textContent).toBe(
      'Verbindingsfout. Probeer opnieuw.',
    )
    expect(box().checked).toBe(false)
  })
})

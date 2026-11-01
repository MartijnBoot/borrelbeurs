// @vitest-environment jsdom
// The board shows active drinks only (Phase 6 T36: SD18; AC23): a drink removed by
// `config` loses its tile and its strip pill, and the other tiles are not remounted.
// The chart is stubbed, and `animate` is a no-op stub (jsdom has none).
// B-10: the sign-up block at the top left of the band (SD6, SD7, SD10, SD11).
import { act, cleanup, render, screen } from '@testing-library/react'
import jsQR from 'jsqr'
import { encode } from 'uqr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applyMessage,
  exchangeStore,
  type ServerMessage,
  type SignupData,
  type SnapshotData,
} from '../exchange'
import { KoersPage } from './KoersPage'
import styles from './KoersPage.module.css'

vi.mock('./ui/DrinkChart', () => ({ DrinkChart: () => <div /> }))

// jsdom's own address is http://localhost:3000, a loopback host: a test that needs a
// page address the block can use sets `address`; null keeps the page's real one.
const page = vi.hoisted(() => ({
  address: null as { origin: string; host: string; hostname: string } | null,
}))
vi.mock('../../components/qr/signupLink', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../components/qr/signupLink')>()
  return { ...actual, pageAddress: () => page.address ?? actual.pageAddress() }
})

const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
  wallet_required: false,
  credit_limit_cents: 0,
}

const DRINKS = [
  { drink_id: 1, name: 'Bier', active: true },
  { drink_id: 2, name: 'Wijn', active: true },
  { drink_id: 3, name: 'Fris', active: true },
]

const price = (cents: number) => ({ price_cents: cents, chart_price_cents: cents })

const SNAPSHOT: SnapshotData = {
  version: 5,
  run: RUN,
  drinks: DRINKS,
  params: {},
  prices: { 1: price(250), 2: price(300), 3: price(150) },
  bars: {},
  news: [],
  earnings: {},
  market_events: [],
}

// hello and snapshot set the baseline seq; a broadcast applies only as the next one (AC18).
let seq = 0

function dispatch(type: ServerMessage['type'], data: unknown) {
  if (type === 'hello') seq = 0
  else if (type !== 'snapshot') seq += 1
  const message = { v: 1, type, seq, ts_ms: 0, run_id: 1, version: 5, data } as ServerMessage
  act(() => exchangeStore.setState((s) => applyMessage(s, message, performance.now()), true))
}

beforeEach(() => {
  Element.prototype.animate = vi.fn(() => ({
    currentTime: 0,
    playbackRate: 1,
    updatePlaybackRate: () => {},
    cancel: () => {},
    pause: () => {},
    play: () => {},
  })) as unknown as Element['animate']
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  dispatch('hello', {
    boot_id: 'B',
    run_id: 1,
    tick_interval_ms: 1000,
    protocol: 1,
    role: 'display',
    theme: {
      preset: 'blauw',
      revision: 0,
      tokens: {},
      font_family: 'sans-serif',
      images: { bg: null, header: null, logo: null, promo: null },
    },
  })
  dispatch('snapshot', SNAPSHOT)
})

afterEach(() => {
  cleanup()
  delete (Element.prototype as Partial<Element>).animate
  page.address = null
})

/** The name nodes of the board's tiles, in order. */
const tileNames = (container: HTMLElement) => [
  ...container.querySelectorAll(`.${styles.tiles} .${styles.name}`),
]

const removeWijn = () =>
  dispatch('config', {
    revision: 4,
    run: { ...RUN, name: 'Vrijmibo' },
    drinks: [DRINKS[0], { ...DRINKS[1], active: false }, DRINKS[2]],
    params: {},
  })

describe('KoersPage', () => {
  it('a config removing a drink removes one tile and keeps the others (SD18)', () => {
    const { container } = render(<KoersPage />)
    const [bier, wijn, fris] = tileNames(container)
    expect([bier, wijn, fris].map((el) => el.textContent)).toEqual(['Bier', 'Wijn', 'Fris'])

    removeWijn()

    // The same DOM nodes: keyed by drink_id, the other tiles are not remounted.
    const after = tileNames(container)
    expect(after).toHaveLength(2)
    expect(after[0]).toBe(bier)
    expect(after[1]).toBe(fris)
    expect(wijn.isConnected).toBe(false)
  })

  it('the price strip lists active drinks only', () => {
    const { container } = render(<KoersPage />)
    removeWijn()
    const strip = [...container.querySelectorAll(`.${styles.tickName}`)].map((el) => el.textContent)
    expect(strip).toEqual(['Bier', 'Fris', 'Bier', 'Fris']) // the row twice over
  })
})

describe('the promo tile (Phase 6 T19: SD29, PD9; AC35)', () => {
  const theme = (revision: number, promo: string | null) => ({
    preset: 'blauw' as const,
    revision,
    tokens: {},
    font_family: 'sans-serif',
    images: { bg: null, header: null, logo: null, promo },
  })
  const container = (root: HTMLElement) => root.querySelector(`.${styles.container}`)!
  const promo = () => document.querySelector('img[alt="Promotie"]')

  it('a theme with images.promo gives has-promo and the promo image; removal drops both', () => {
    const { container: root } = render(<KoersPage />)
    expect(container(root).classList.contains('has-promo')).toBe(false)
    expect(promo()).toBeNull()

    act(() => exchangeStore.setState({ theme: theme(1, '/assets/9') }))
    expect(container(root).classList.contains('has-promo')).toBe(true)
    expect(promo()?.getAttribute('src')).toBe('/assets/9')

    act(() => exchangeStore.setState({ theme: theme(2, null) }))
    expect(container(root).classList.contains('has-promo')).toBe(false)
    expect(promo()).toBeNull()
  })
})

describe('a closed run (Phase 7 T17: SD2, PD5; AC3)', () => {
  const closeRun = () => dispatch('run_closed', { run_id: 1, name: 'Vrijmibo', ended_at_ms: 0 })

  it('run_closed after a snapshot shows "Borrel afgelopen", calm: no tiles, no marquee', () => {
    const { container } = render(<KoersPage />)
    expect(tileNames(container)).toHaveLength(3)

    closeRun()

    expect(container.textContent).toContain('Borrel afgelopen')
    expect(container.textContent).not.toContain('Geen actieve borrel')
    expect(tileNames(container)).toHaveLength(0)
    expect(container.querySelector(`.${styles.tickName}`)).toBeNull()
  })

  it('a later snapshot restores the board, without a remount', () => {
    const { container } = render(<KoersPage />)
    closeRun()
    dispatch('snapshot', SNAPSHOT)

    expect(container.textContent).not.toContain('Borrel afgelopen')
    expect(tileNames(container).map((el) => el.textContent)).toEqual(['Bier', 'Wijn', 'Fris'])
  })

  it('with no run and nothing closed it still says "Geen actieve borrel"', () => {
    dispatch('hello', {
      boot_id: 'C',
      run_id: null,
      tick_interval_ms: 1000,
      protocol: 1,
      role: 'display',
      theme: exchangeStore.getState().theme,
    })
    const { container } = render(<KoersPage />)
    expect(container.textContent).toContain('Geen actieve borrel')
    expect(container.textContent).not.toContain('Borrel afgelopen')
  })
})

describe('the sign-up block (B-10 SD6, SD7, SD10, SD11; AC11-AC14, AC17, AC18)', () => {
  const LAN = { origin: 'http://192.168.8.10', host: '192.168.8.10', hostname: '192.168.8.10' }
  const ON: SignupData = { show_on_screen: true, signup_code: 'BORREL', public_url: null }
  const signup = (data: SignupData) => dispatch('signup', data)
  const block = () => screen.queryByRole('img', { name: 'Aanmeld-QR-code' })
  const band = (root: HTMLElement) => root.querySelector(`.${styles.band}`)

  // The QR code rendered to pixels, as a camera would see it, then read with jsqr.
  function decode(svg: Element, k = 6) {
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
  const cells = (svg: Element) =>
    Array.from(svg.querySelectorAll('rect'), (r) => `${r.getAttribute('x')},${r.getAttribute('y')}`)
  const expectedCells = (link: string) =>
    encode(link, { ecc: 'Q', border: 4 }).data.flatMap((row, y) =>
      row.flatMap((dark, x) => (dark ? [`${x},${y}`] : [])),
    )

  beforeEach(() => {
    page.address = LAN
  })

  const noRun = (role: 'display' | 'admin' = 'display') =>
    dispatch('hello', {
      boot_id: 'C',
      run_id: null,
      tick_interval_ms: 1000,
      protocol: 1,
      role,
      theme: exchangeStore.getState().theme,
    })

  it('shows for the switch on, a code and an address, at the left of the marquees (AC11)', () => {
    const { container } = render(<KoersPage />)
    signup(ON)

    expect(block()).not.toBeNull()
    const row = band(container)!
    expect(row.firstElementChild?.contains(block())).toBe(true)
    expect(row.lastElementChild?.classList.contains(styles.marquees)).toBe(true)
    expect(row.lastElementChild?.querySelector(`.${styles.tickName}`)).not.toBeNull()
  })

  it.each<[string, SignupData, typeof LAN | null]>([
    ['the switch off', { ...ON, show_on_screen: false }, LAN],
    ['no code', { ...ON, signup_code: null }, LAN],
    ['a blank code', { ...ON, signup_code: '  ' }, LAN],
    ['no address: a loopback page and no public_url (AC3)', ON, null],
  ])('%s shows no block (AC13)', (_, data, address) => {
    page.address = address
    const { container } = render(<KoersPage />)
    signup(data)

    expect(block()).toBeNull()
    expect(band(container)!.children).toHaveLength(1) // the marquees only
  })

  it('with no block and no marquees there is no band, so it takes no space (AC13, F9)', () => {
    noRun()
    const { container } = render(<KoersPage />)
    signup({ ...ON, show_on_screen: false })

    expect(band(container)).toBeNull()
  })

  it('before any signup message there is no block', () => {
    render(<KoersPage />)
    expect(block()).toBeNull()
  })

  it('with a public_url it shows at a loopback page, and links there (AC2)', () => {
    page.address = null
    render(<KoersPage />)
    signup({ ...ON, public_url: 'http://192.168.8.10' })

    expect(decode(block()!)).toBe('http://192.168.8.10/speler?code=BORREL')
  })

  it('decodes to the link, drawn at Q with a 4-module quiet zone, over "Meld je aan" (AC12)', () => {
    const link = `${LAN.origin}/speler?code=${encodeURIComponent('a b&c#é')}`
    render(<KoersPage />)
    signup({ ...ON, signup_code: 'a b&c#é' })

    const svg = block()!
    expect(decode(svg)).toBe(link)
    const modules = encode(link, { ecc: 'Q', border: 4 }).data
    expect(svg.getAttribute('viewBox')).toBe(`0 0 ${modules.length} ${modules.length}`)
    expect(cells(svg)).toEqual(expectedCells(link))
    const card = svg.parentElement!
    expect(card.textContent).toBe('Meld je aan')
  })

  it('shows alone with no live run, and after a close (AC14)', () => {
    noRun()
    const { container } = render(<KoersPage />)
    signup(ON)
    expect(block()).not.toBeNull()
    expect(band(container)!.children).toHaveLength(1) // the block only

    dispatch('snapshot', SNAPSHOT)
    dispatch('run_closed', { run_id: 1, name: 'Vrijmibo', ended_at_ms: 0 })
    expect(container.textContent).toContain('Borrel afgelopen')
    expect(block()).not.toBeNull()
  })

  it.each(['crash', 'bubble', 'correction'])('stays through a %s (AC14)', (kind) => {
    render(<KoersPage />)
    signup(ON)
    const before = block()
    dispatch('market_event', {
      op: 'start',
      event_id: 1,
      kind,
      drink_ids: [1],
      t_start_ms: 0,
      t_end_ms: Date.now() + 60_000,
    })

    expect(document.querySelector('.market-banner')).not.toBeNull()
    expect(block()).toBe(before)
  })

  it('a new code redraws it; a clear or the switch off removes it (AC18)', () => {
    render(<KoersPage />)
    signup(ON)
    expect(decode(block()!)).toBe(`${LAN.origin}/speler?code=BORREL`)

    signup({ ...ON, signup_code: 'ANDERS' })
    expect(decode(block()!)).toBe(`${LAN.origin}/speler?code=ANDERS`)

    signup({ ...ON, signup_code: null })
    expect(block()).toBeNull()
    signup(ON)
    expect(block()).not.toBeNull()
    signup({ ...ON, show_on_screen: false })
    expect(block()).toBeNull()
  })

  it('admin sees the same block as a display key: the page does not read the role (AC17)', () => {
    const shown = (role: 'display' | 'admin') => {
      noRun(role)
      signup(ON)
      const { container } = render(<KoersPage />)
      const html = band(container)!.outerHTML
      cleanup()
      return html
    }
    expect(shown('admin')).toBe(shown('display'))
  })
})

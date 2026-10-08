// @vitest-environment jsdom
// The board shows active drinks only (Phase 6 T36: SD18; AC23): a drink removed by
// `config` loses its tile and its strip pill, and the other tiles are not remounted.
// The chart is stubbed, and `animate` is a no-op stub (jsdom has none).
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyMessage, exchangeStore, type ServerMessage, type SnapshotData } from '../exchange'
import { KoersPage } from './KoersPage'
import styles from './KoersPage.module.css'

vi.mock('./ui/DrinkChart', () => ({ DrinkChart: () => <div /> }))

const RUN = {
  run_id: 1,
  tick_interval_ms: 1000,
  candle_interval_ms: 60000,
  quote_grace_versions: 2,
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

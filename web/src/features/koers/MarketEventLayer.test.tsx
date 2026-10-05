// @vitest-environment jsdom
// Market events and the marquees on the composed board (AC30-AC33). The chart
// is T19's and is stubbed; jsdom has no Web Animations API, so
// `Element.prototype.animate` is a recording stub.
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ExchangeState, type MarketEventInfo } from '../exchange'
import { KoersPage } from './KoersPage'

vi.mock('./ui/DrinkChart', () => ({ DrinkChart: () => <div /> }))

interface FakeAnimation {
  keyframes: Keyframe[]
  currentTime: number | null
  playbackRate: number
}

const animations: FakeAnimation[] = []
const XSS = '<img src=x onerror=alert(1)>'
const OFFSET = 300_000 // the client's clock five minutes behind the server's

const price = (cents: number) => ({ price_cents: cents, chart_price_cents: cents })

function event(kind: MarketEventInfo['kind'], start: number, end: number): MarketEventInfo {
  return { event_id: 7, kind, drink_ids: [1], t_start_ms: start, t_end_ms: end }
}

/** The server's clock as the client knows it. */
const serverNow = () => Date.now() + exchangeStore.getState().skewOffsetMs

function set(patch: Partial<ExchangeState>) {
  act(() => exchangeStore.setState(patch))
}

const overlay = () => document.querySelector('.market-overlay')
const banner = () => document.querySelector('.market-banner')
const board = (container: HTMLElement) => container.querySelector('[data-market]')
const newsAnimation = () =>
  animations.find((a) => a.keyframes[0].transform === 'translateX(100vw)')!

beforeEach(() => {
  vi.useFakeTimers({ now: 1_700_000_000_000 })
  animations.length = 0
  Element.prototype.animate = vi.fn((keyframes: Keyframe[]) => {
    const animation = {
      keyframes,
      currentTime: 0,
      playbackRate: 1,
      updatePlaybackRate: (rate: number) => {
        animation.playbackRate = rate
      },
      cancel: () => {},
      pause: () => {},
      play: () => {},
    }
    animations.push(animation)
    return animation as unknown as Animation
  }) as unknown as Element['animate']
  exchangeStore.setState(
    {
      ...exchangeStore.getInitialState(),
      skewOffsetMs: OFFSET,
      drinks: [{ drink_id: 1, name: 'Bier' }],
      prices: { 1: price(280) },
      prevPriceCents: { 1: 250 },
    },
    true,
  )
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  delete (Element.prototype as Partial<Element>).animate
})

describe('MarketEventLayer', () => {
  it('renders a crash: overlay, banner, shaking tiles (AC31)', () => {
    set({ marketEvents: [event('crash', serverNow() - 1_000, serverNow() + 60_000)] })
    const { container } = render(<KoersPage />)
    expect(overlay()?.classList.contains('crash')).toBe(true)
    expect(banner()?.textContent).toBe('⚠ MARKTCRASH')
    expect(board(container)?.getAttribute('data-market')).toBe('crash')
  })

  it('renders a bubble: overlay, banner, pulsing tiles (AC31)', () => {
    set({ marketEvents: [event('bubble', serverNow() - 1_000, serverNow() + 60_000)] })
    const { container } = render(<KoersPage />)
    expect(overlay()?.classList.contains('bubble')).toBe(true)
    expect(banner()?.textContent).toBe('▲ PRIJSBUBBEL')
    expect(board(container)?.getAttribute('data-market')).toBe('bubble')
  })

  it('renders a correction as a calm banner: no overlay, no animation (AC31)', () => {
    set({ marketEvents: [event('correction', serverNow() - 1_000, serverNow() + 60_000)] })
    const { container } = render(<KoersPage />)
    expect(banner()?.textContent).toBe('Terug naar start')
    expect(overlay()).toBeNull()
    expect(board(container)).toBeNull()
    expect(newsAnimation().playbackRate).toBe(1)
  })

  it('ends the event at t_end_ms on server time, with no broadcast (AC30)', () => {
    set({ marketEvents: [event('crash', serverNow() - 1_000, serverNow() + 10_000)] })
    render(<KoersPage />)

    act(() => vi.advanceTimersByTime(9_999))
    expect(banner()).not.toBeNull()
    act(() => vi.advanceTimersByTime(1_500))
    // 1.5 s past t_end on the server's clock; on the client's own it is still
    // five minutes before. The store still holds the event: no `end` came.
    expect(banner()).toBeNull()
    expect(overlay()).toBeNull()
    expect(exchangeStore.getState().marketEvents).toHaveLength(1)
  })

  it('re-arms the end when the clock offset changes (AC30)', () => {
    set({ marketEvents: [event('crash', serverNow() - 1_000, serverNow() + 10_000)] })
    render(<KoersPage />)

    set({ skewOffsetMs: OFFSET + 5_000 }) // the server is 5 s further along than thought
    act(() => vi.advanceTimersByTime(5_000))
    expect(banner()).toBeNull()
  })

  it('treats a late end broadcast as a no-op', () => {
    set({ marketEvents: [event('crash', serverNow() - 1_000, serverNow() + 1_000)] })
    render(<KoersPage />)
    act(() => vi.advanceTimersByTime(1_000))
    expect(banner()).toBeNull()

    set({ marketEvents: [] })
    expect(banner()).toBeNull()
  })

  it('runs the news marquee at 2.5 during a crash and back at 1 after (AC33)', () => {
    set({ marketEvents: [event('crash', serverNow() - 1_000, serverNow() + 10_000)] })
    render(<KoersPage />)
    expect(newsAnimation().playbackRate).toBe(2.5)

    act(() => vi.advanceTimersByTime(10_000))
    expect(newsAnimation().playbackRate).toBe(1)
  })

  it('runs the news marquee at 2.5 during a bubble (AC33)', () => {
    set({ marketEvents: [event('bubble', serverNow() - 1_000, serverNow() + 10_000)] })
    render(<KoersPage />)
    expect(newsAnimation().playbackRate).toBe(2.5)
  })
})

describe('marquees', () => {
  it('render news text as text, never as HTML (AC32)', () => {
    set({ news: [{ news_id: 1, ts_ms: serverNow(), level: 'danger', text: XSS }] })
    const { container } = render(<KoersPage />)
    expect(screen.getByText(XSS)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('shows "Geen nieuws" with no news', () => {
    render(<KoersPage />)
    expect(screen.getByText('Geen nieuws')).toBeTruthy()
  })

  it('shows each drink with price and delta, twice for a seamless loop', () => {
    set({ drinks: [{ drink_id: 1, name: XSS }] })
    const { container } = render(<KoersPage />)
    // the tile's name and the marquee's two copies, all text
    expect(screen.getAllByText(XSS)).toHaveLength(3)
    expect(container.querySelector('img')).toBeNull()
  })
})

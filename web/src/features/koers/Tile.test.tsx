// @vitest-environment jsdom
// The board's tiles and empty state (AC26, AC32, AC34). The chart is T19's
// and the marquees T21's (MarketEventLayer.test.tsx); both are stubbed here.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ExchangeState } from '../exchange'
import { KoersPage } from './KoersPage'
import { Tile } from './Tile'

vi.mock('./ui/DrinkChart', () => ({
  DrinkChart: ({ drinkId }: { drinkId: number }) => <div data-testid={`chart-${drinkId}`} />,
}))
vi.mock('./PriceMarquee', () => ({ PriceMarquee: () => null }))
vi.mock('./NewsMarquee', () => ({ NewsMarquee: () => null }))

const NBSP = ' '
const XSS = '<img src=x onerror=alert(1)>'

const price = (cents: number) => ({ price_cents: cents, chart_price_cents: cents })

function live(patch: Partial<ExchangeState> = {}): Partial<ExchangeState> {
  return {
    empty: false,
    drinks: [
      { drink_id: 1, name: 'Bier' },
      { drink_id: 2, name: 'Wijn' },
    ],
    prices: { 1: price(260), 2: price(300) },
    prevPriceCents: { 1: 260, 2: 300 },
    ...patch,
  }
}

// jsdom has no AnimationEvent, so React listens for the prefixed name there; a
// browser sends `animationend`. Firing both covers either.
function endAnimation(element: Element) {
  fireEvent.animationEnd(element)
  fireEvent(element, new Event('webkitAnimationEnd', { bubbles: true }))
}

function set(patch: Partial<ExchangeState>) {
  act(() => exchangeStore.setState(patch))
}

beforeEach(() => {
  exchangeStore.setState({ ...exchangeStore.getInitialState(), ...live() }, true)
})

afterEach(cleanup)

describe('Tile', () => {
  it('shows name, price and delta', () => {
    set({ prices: { 1: price(280), 2: price(300) }, prevPriceCents: { 1: 250, 2: 300 } })
    const { container } = render(<Tile drinkId={1} />)
    // textContent, exactly: the queries would collapse Intl's no-break space.
    const [name, priceText, delta] = [...container.firstElementChild!.children].map(
      (c) => c.textContent,
    )
    expect([name, priceText, delta]).toEqual(['Bier', `€${NBSP}2,80`, `▲ €${NBSP}0,30 (12,0%)`])
  })

  it('renders an HTML name as text and creates no element (AC32)', () => {
    set({ drinks: [{ drink_id: 1, name: XSS }] })
    const { container } = render(<Tile drinkId={1} />)
    expect(screen.getByText(XSS)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })

  it('pulses rising when the displayed price goes up (AC26)', () => {
    const { container } = render(<Tile drinkId={1} />)
    const tile = container.firstElementChild!
    set({ prices: { 1: price(270), 2: price(300) }, prevPriceCents: { 1: 260, 2: 300 } })
    expect(tile.getAttribute('data-pulse')).toBe('rising')
  })

  it('pulses falling when it goes down', () => {
    const { container } = render(<Tile drinkId={1} />)
    set({ prices: { 1: price(250), 2: price(300) }, prevPriceCents: { 1: 260, 2: 300 } })
    expect(container.firstElementChild!.getAttribute('data-pulse')).toBe('falling')
  })

  it('does not pulse on a snapshot', () => {
    const { container } = render(<Tile drinkId={1} />)
    // a snapshot replaces prices and sets prev = current
    set({ prices: { 1: price(400), 2: price(300) }, prevPriceCents: { 1: 400, 2: 300 } })
    expect(container.firstElementChild!.getAttribute('data-pulse')).toBeNull()
  })

  it('clears the pulse when its animation ends, and pulses again on the next change', () => {
    const { container } = render(<Tile drinkId={1} />)
    const tile = container.firstElementChild!
    set({ prices: { 1: price(270), 2: price(300) }, prevPriceCents: { 1: 260, 2: 300 } })
    endAnimation(tile)
    expect(tile.getAttribute('data-pulse')).toBeNull()
    set({ prices: { 1: price(280), 2: price(300) }, prevPriceCents: { 1: 270, 2: 300 } })
    expect(tile.getAttribute('data-pulse')).toBe('rising')
  })
})

describe('KoersPage', () => {
  it('shows the legend verbatim and one tile per drink, in order', () => {
    render(<KoersPage />)
    expect(screen.getByText('Tegels pulseren bij stijging (rood) of daling (groen).')).toBeTruthy()
    expect(screen.getAllByTestId(/^chart-/).map((c) => c.dataset.testid)).toEqual([
      'chart-1',
      'chart-2',
    ])
  })

  it('shows the empty state, then the board after a snapshot without remounting (AC34)', () => {
    exchangeStore.setState({ ...exchangeStore.getInitialState(), empty: true }, true)
    const { container } = render(<KoersPage />)
    const page = container.firstElementChild
    expect(screen.getByText('Geen actieve borrel')).toBeTruthy()
    expect(screen.queryAllByTestId(/^chart-/)).toHaveLength(0)

    set(live())
    expect(screen.queryByText('Geen actieve borrel')).toBeNull()
    expect(screen.getAllByTestId(/^chart-/)).toHaveLength(2)
    expect(container.firstElementChild).toBe(page)
  })
})

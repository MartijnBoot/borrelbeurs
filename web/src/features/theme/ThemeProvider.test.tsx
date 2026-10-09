// @vitest-environment jsdom
// The store's theme reaches the document without a reload (AC3, AC7, AC10).
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { exchangeStore, type ThemeData } from '../exchange'
import { ThemeProvider } from './ThemeProvider'

// The provider applies whatever the server sends; 24 made-up tokens prove it
// sets every one without the client holding any preset data (SD6).
const blauw: ThemeData = {
  preset: 'blauw',
  revision: 0,
  tokens: Object.fromEntries(Array.from({ length: 24 }, (_, i) => [`--t${i}`, `#0000${10 + i}`])),
  font_family: 'Inter, system-ui, sans-serif',
  images: { bg: null, header: null, logo: null, promo: null },
}
const GARAMOND = "'EB Garamond', Georgia, serif"

function theme(revision: number, change: Partial<ThemeData> = {}): ThemeData {
  return { ...blauw, revision, ...change }
}

function setTheme(next: ThemeData) {
  act(() => exchangeStore.setState({ theme: next }))
}

const root = () => document.documentElement.style

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  document.documentElement.removeAttribute('style')
  document.body.removeAttribute('style')
  render(<ThemeProvider>child</ThemeProvider>)
})

afterEach(cleanup)

describe('ThemeProvider', () => {
  it('sets every token of a theme on the root element', () => {
    setTheme(theme(1))
    const tokens = Object.entries(blauw.tokens)
    expect(tokens).toHaveLength(24)
    for (const [name, value] of tokens) expect(root().getPropertyValue(name)).toBe(value)
    expect(document.body.style.fontFamily).toBe(blauw.font_family)
  })

  it('applies a later revision over an earlier one', () => {
    setTheme(theme(1))
    setTheme(theme(2, { tokens: { ...blauw.tokens, '--t0': '#123456' } }))
    expect(root().getPropertyValue('--t0')).toBe('#123456')
  })

  it('ignores a lower revision', () => {
    setTheme(theme(3, { tokens: { ...blauw.tokens, '--t0': '#333333' } }))
    setTheme(theme(2, { tokens: { ...blauw.tokens, '--t0': '#222222' } }))
    expect(root().getPropertyValue('--t0')).toBe('#333333')
  })

  it('sets the EB Garamond stack for Oud Geld', () => {
    setTheme(theme(1, { preset: 'oudgeld', font_family: GARAMOND }))
    // The CSSOM normalises the stack's quotes to double ones.
    expect(document.body.style.fontFamily).toBe('"EB Garamond", Georgia, serif')
  })

  it('sets each set image slot as --img-*, and resets it when null (Phase 6 PD9)', () => {
    setTheme(theme(1, { images: { ...blauw.images, logo: '/assets/7', promo: '/assets/9' } }))
    expect(root().getPropertyValue('--img-logo')).toBe('url("/assets/7")')
    expect(root().getPropertyValue('--img-promo')).toBe('url("/assets/9")')
    expect(root().getPropertyValue('--img-bg')).toBe('initial')

    setTheme(theme(2, { images: { ...blauw.images, promo: '/assets/9' } }))
    // `initial` (not removed) beats the `:root` value `/theme.css` loaded with, so
    // `var(--img-logo, bundled)` falls back to the bundled logo.
    expect(root().getPropertyValue('--img-logo')).toBe('initial')
    expect(root().getPropertyValue('--img-promo')).toBe('url("/assets/9")')
  })

  it('flags the bg and header slots on <html> so the static rules paint them live', () => {
    const html = document.documentElement
    setTheme(theme(1, { images: { ...blauw.images, bg: '/assets/1', header: '/assets/2' } }))
    expect(html.hasAttribute('data-img-bg')).toBe(true)
    expect(html.hasAttribute('data-img-header')).toBe(true)

    setTheme(theme(2, { images: { ...blauw.images, header: '/assets/2' } }))
    expect(html.hasAttribute('data-img-bg')).toBe(false)
    expect(html.hasAttribute('data-img-header')).toBe(true)

    setTheme(theme(3))
    expect(html.hasAttribute('data-img-header')).toBe(false)
  })

  it('leaves /theme.css in charge until a theme arrives', () => {
    expect(document.documentElement.getAttribute('style')).toBeNull()
    expect(document.body.getAttribute('style')).toBeNull()
  })
})

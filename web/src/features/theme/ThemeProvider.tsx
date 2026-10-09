/**
 * Live re-theming (AC3, SD7). `/theme.css` themes the first paint; after that
 * the store's theme -- from `hello`, a `theme` broadcast or the catch-up
 * unicast -- is written onto the document: every token as an inline custom
 * property on `<html>`, and the font stack on `<body>`. Inline properties win
 * over `/theme.css`, so no reload is needed.
 *
 * The image slots (Phase 6 PD9) are `--img-<slot>` the same way: set to the
 * server's `/assets/<id>`, or `initial` when null, so the bundled fallbacks
 * apply. `data-img-<slot>` on `<html>` switches on `base.css`'s bg and header
 * rules, which `/theme.css` only writes for slots set when it loaded.
 *
 * The client holds no preset data (SD6): what is applied is exactly what the
 * server sent. A revision not higher than the last applied one is ignored
 * (AC7) -- the reducer already keeps only higher ones; this is the same rule
 * at the DOM.
 */
import { useEffect, type ReactNode } from 'react'
import { exchangeStore, selectTheme, type ThemeData } from '../exchange'

function apply(theme: ThemeData): void {
  const root = document.documentElement.style
  for (const [name, value] of Object.entries(theme.tokens)) root.setProperty(name, value)
  const html = document.documentElement
  for (const [slot, url] of Object.entries(theme.images)) {
    // `initial`, not removed: removing the inline value would let the `:root`
    // value `/theme.css` loaded with apply again (a deleted asset's url).
    root.setProperty(`--img-${slot}`, url === null ? 'initial' : `url("${url}")`)
    html.toggleAttribute(`data-img-${slot}`, url !== null)
  }
  document.body.style.fontFamily = theme.font_family
}

export function ThemeProvider({ children }: { children?: ReactNode }) {
  useEffect(() => {
    let applied = -1
    const sync = (theme: ThemeData | null) => {
      if (theme === null || theme.revision <= applied) return
      applied = theme.revision
      apply(theme)
    }
    sync(selectTheme(exchangeStore.getState()))
    return exchangeStore.subscribe((state) => sync(selectTheme(state)))
  }, [])

  return children
}

/**
 * Whether a CSS media query matches, live (Phase 5 PD15): `matchMedia` with a
 * `change` listener. The revenue chart uses it to skip construction and the
 * fetch at ≤640 px (SD17) -- CSS-only hiding was v1's bug (`bar.html:34`).
 * Shared since Phase 6 (T22): `MobileSectionNav` switches to a select with it.
 */
import { useCallback, useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
}

/**
 * Where an explanation popup goes (B-01 PD5): below its (i), or above it when
 * it does not fit below, and never closer than `MARGIN` to a viewport edge. The
 * popup's CSS caps its width at `min(20rem, 100vw - 16px)` and its height at
 * `100vh - 16px`, so a box that is clamped here always fits.
 */
export const MARGIN = 8
const GAP = 6

export interface Size {
  width: number
  height: number
}

export interface Anchor {
  left: number
  top: number
  bottom: number
}

export function placePopup(
  anchor: Anchor,
  popup: Size,
  viewport: Size,
): { left: number; top: number } {
  const clamp = (value: number, max: number) => Math.max(MARGIN, Math.min(value, max))
  const left = clamp(anchor.left, viewport.width - MARGIN - popup.width)
  const below = anchor.bottom + GAP
  const above = anchor.top - GAP - popup.height
  let top: number
  if (below + popup.height <= viewport.height - MARGIN) top = below
  else if (above >= MARGIN) top = above
  else top = clamp(viewport.height - MARGIN - popup.height, viewport.height)
  return { left, top }
}

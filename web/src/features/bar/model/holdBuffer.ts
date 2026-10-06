/**
 * The hold buffer (Phase 5 SD1, SD3): which `Quote` the pad displays.
 *
 * With no hold running, every offered quote is displayed at once. A press
 * starts a hold; while it runs, offers update only `latest`. The hold ends
 * `HOLD_MS` after the last release, or `HOLD_MAX_MS` after it began, whichever
 * comes first -- then `latest` is displayed. `promote()` displays `latest` at
 * once (SD3's force-promotions) and keeps the hold's timers running.
 *
 * Pure and timer-injected: no clock, no DOM, so it runs under a fake
 * scheduler. It holds `Quote` references only, never separate fields (SD2).
 */
import type { Quote } from '../../exchange'
import { AGE_SHOW_MS, HOLD_MAX_MS, HOLD_MS, STALE_MS } from './constants'

export interface HoldBufferDeps<Id = unknown> {
  setTimeout(fn: () => void, ms: number): Id
  clearTimeout(id: Id): void
  /** Called after every change to `displayed` or `latest`. */
  onChange(): void
}

export interface HoldBuffer {
  readonly displayed: Quote | null
  readonly latest: Quote | null
  offer(latest: Quote | null): void
  pressStart(): void
  pressEnd(): void
  promote(): void
  dispose(): void
}

export function createHoldBuffer<Id>(deps: HoldBufferDeps<Id>): HoldBuffer {
  let displayed: Quote | null = null
  let latest: Quote | null = null
  let holding = false
  let pressed = false
  let releaseTimer: Id | null = null
  let maxTimer: Id | null = null

  function clearRelease() {
    if (releaseTimer !== null) deps.clearTimeout(releaseTimer)
    releaseTimer = null
  }

  function endHold() {
    clearRelease()
    if (maxTimer !== null) deps.clearTimeout(maxTimer)
    maxTimer = null
    holding = false
    pressed = false
    displayed = latest
    deps.onChange()
  }

  return {
    get displayed() {
      return displayed
    },
    get latest() {
      return latest
    },
    offer(quote) {
      latest = quote
      if (!holding) displayed = quote
      deps.onChange()
    },
    pressStart() {
      pressed = true
      clearRelease()
      if (!holding) {
        holding = true
        maxTimer = deps.setTimeout(endHold, HOLD_MAX_MS)
      }
    },
    pressEnd() {
      if (!holding || !pressed) return
      pressed = false
      clearRelease()
      releaseTimer = deps.setTimeout(endHold, HOLD_MS)
    },
    promote() {
      displayed = latest
      deps.onChange()
    },
    dispose() {
      clearRelease()
      if (maxTimer !== null) deps.clearTimeout(maxTimer)
      maxTimer = null
    },
  }
}

/** Monotonic ms since the displayed quote arrived (SD4). */
export function ageMs(displayed: Quote, now: number): number {
  return now - displayed.receivedAt
}

/** The age line and "Ververs" show above `AGE_SHOW_MS` (SD4, AC7). */
export function showAge(displayed: Quote | null, now: number): boolean {
  return displayed !== null && ageMs(displayed, now) > AGE_SHOW_MS
}

/** The pad is disabled when the latest quote is missing or older than `STALE_MS` (SD4, AC8). */
export function isStale(latest: Quote | null, now: number): boolean {
  return latest === null || now - latest.receivedAt > STALE_MS
}

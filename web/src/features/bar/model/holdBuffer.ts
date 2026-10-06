/**
 * The hold buffer (Phase 5 SD1, SD3): which `Quote` the pad displays.
 *
 * With no hold running, every offered quote is displayed at once. A press
 * starts a hold; while it runs, offers update only `latest`. Presses are
 * tracked by id (a pointer id, or one id for the keyboard), so the hold ends
 * `HOLD_MS` after the last release of *all* of them, or `HOLD_MAX_MS` after it began, whichever
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

/** One finger or key; releasing an id that is not down is a no-op. */
export type PressId = string | number

export interface HoldBuffer {
  readonly displayed: Quote | null
  readonly latest: Quote | null
  offer(latest: Quote | null): void
  pressStart(id?: PressId): void
  pressEnd(id?: PressId): void
  promote(): void
  dispose(): void
}

export function createHoldBuffer<Id>(deps: HoldBufferDeps<Id>): HoldBuffer {
  let displayed: Quote | null = null
  let latest: Quote | null = null
  let holding = false
  const pressed = new Set<PressId>()
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
    pressed.clear()
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
    pressStart(id = 0) {
      pressed.add(id)
      clearRelease()
      if (!holding) {
        holding = true
        maxTimer = deps.setTimeout(endHold, HOLD_MAX_MS)
      }
    },
    pressEnd(id = 0) {
      if (!holding || !pressed.delete(id) || pressed.size > 0) return
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

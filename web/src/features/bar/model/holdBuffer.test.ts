// The hold buffer on an injected fake clock (Phase 5 T6): SD1, SD3, SD4.
import { beforeEach, describe, expect, it } from 'vitest'
import { quoteFromPriceChanged, type Quote } from '../../exchange'
import { AGE_SHOW_MS, HOLD_MAX_MS, HOLD_MS, STALE_MS } from './constants'
import { createHoldBuffer, isStale, showAge, type HoldBuffer } from './holdBuffer'

function quote(version: number, receivedAt = 0): Quote {
  return quoteFromPriceChanged(
    { version, prices: [{ drink_id: 1, price_cents: version }] },
    receivedAt,
  )
}

/** A deterministic scheduler: `advance` fires due timers in time order. */
function fakeClock() {
  let now = 0
  let nextId = 1
  const timers = new Map<number, { at: number; fn: () => void }>()
  return {
    now: () => now,
    setTimeout: (fn: () => void, ms: number) => {
      const id = nextId++
      timers.set(id, { at: now + ms, fn })
      return id
    },
    clearTimeout: (id: number) => void timers.delete(id),
    advance(ms: number) {
      const end = now + ms
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, t]) => t.at <= end)
          .sort(([, a], [, b]) => a.at - b.at)[0]
        if (due === undefined) break
        timers.delete(due[0])
        now = due[1].at
        due[1].fn()
      }
      now = end
    },
    pending: () => timers.size,
  }
}

let clock: ReturnType<typeof fakeClock>
let changes: number
let buffer: HoldBuffer

beforeEach(() => {
  clock = fakeClock()
  changes = 0
  buffer = createHoldBuffer({
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    onChange: () => changes++,
  })
})

describe('the hold buffer', () => {
  it('with no press displays every offer at once (AC4)', () => {
    const [a, b] = [quote(1), quote(2)]
    buffer.offer(a)
    expect(buffer.displayed).toBe(a)
    buffer.offer(b)
    expect(buffer.displayed).toBe(b)
    expect(buffer.latest).toBe(b)
    expect(changes).toBe(2)
  })

  it('holds through a press and shows the latest HOLD_MS after the release (AC5)', () => {
    const [a, b, c] = [quote(1), quote(2), quote(3)]
    buffer.offer(a)
    buffer.pressStart()
    buffer.offer(b)
    clock.advance(500)
    buffer.pressEnd()
    buffer.offer(c)
    expect(buffer.displayed).toBe(a)
    expect(buffer.latest).toBe(c)
    clock.advance(HOLD_MS - 1)
    expect(buffer.displayed).toBe(a)
    clock.advance(1)
    expect(buffer.displayed).toBe(c)
    expect(clock.pending()).toBe(0)
  })

  it('a second press inside the hold extends it from the new release', () => {
    buffer.offer(quote(1))
    buffer.pressStart()
    buffer.pressEnd()
    clock.advance(1500)
    buffer.pressStart()
    buffer.offer(quote(2))
    buffer.pressEnd()
    clock.advance(HOLD_MS - 1)
    expect(buffer.displayed?.version).toBe(1)
    clock.advance(1)
    expect(buffer.displayed?.version).toBe(2)
  })

  it('continuous presses end the hold HOLD_MAX_MS after it began (AC5)', () => {
    buffer.offer(quote(1))
    buffer.pressStart()
    for (let t = 0; t < HOLD_MAX_MS - 1000; t += 1000) {
      buffer.offer(quote(2 + t))
      buffer.pressEnd()
      clock.advance(1000)
      buffer.pressStart()
    }
    clock.advance(999)
    expect(buffer.displayed?.version).toBe(1)
    clock.advance(1)
    expect(buffer.displayed).toBe(buffer.latest)
    expect(buffer.displayed?.version).not.toBe(1)
    // The hold is over: a fresh offer shows at once, and the release starts no new hold.
    buffer.pressEnd()
    buffer.offer(quote(999))
    expect(buffer.displayed?.version).toBe(999)
  })

  it('promote() mid-hold shows the latest and the hold still ends on its timers (AC6)', () => {
    buffer.offer(quote(1))
    buffer.pressStart()
    buffer.offer(quote(2))
    buffer.promote()
    expect(buffer.displayed?.version).toBe(2)
    buffer.offer(quote(3))
    expect(buffer.displayed?.version).toBe(2) // still holding
    buffer.pressEnd()
    clock.advance(HOLD_MS)
    expect(buffer.displayed?.version).toBe(3)
  })

  it('an offer of null keeps nothing displayed', () => {
    buffer.offer(null)
    expect(buffer.displayed).toBeNull()
  })

  it('dispose() cancels the running timers', () => {
    buffer.offer(quote(1))
    buffer.pressStart()
    buffer.pressEnd()
    expect(clock.pending()).toBeGreaterThan(0)
    buffer.dispose()
    expect(clock.pending()).toBe(0)
  })
})

describe('age and staleness (SD4)', () => {
  it('showAge is true only above AGE_SHOW_MS on the displayed quote (AC7)', () => {
    const q = quote(1, 1_000)
    expect(showAge(q, 1_000 + AGE_SHOW_MS)).toBe(false)
    expect(showAge(q, 1_001 + AGE_SHOW_MS)).toBe(true)
    expect(showAge(null, 1_000_000)).toBe(false)
  })

  it('isStale is true above STALE_MS on the latest quote (AC8)', () => {
    const q = quote(1, 1_000)
    expect(isStale(q, 1_000 + STALE_MS)).toBe(false)
    expect(isStale(q, 1_001 + STALE_MS)).toBe(true)
  })

  it('a null latest is stale', () => {
    expect(isStale(null, 0)).toBe(true)
  })
})

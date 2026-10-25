// @vitest-environment jsdom
// The player page's refresh (B-05 SD21, AC10).
import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { POLL_MS, useVisiblePoll } from './useVisiblePoll'

let visibility: DocumentVisibilityState

function setVisibility(state: DocumentVisibilityState) {
  visibility = state
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  vi.useFakeTimers()
  visibility = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useVisiblePoll (AC10)', () => {
  it('loads every 10 s while visible', () => {
    const load = vi.fn()
    renderHook(() => useVisiblePoll(load))
    expect(POLL_MS).toBe(10_000)
    vi.advanceTimersByTime(9_999)
    expect(load).toHaveBeenCalledTimes(0)
    vi.advanceTimersByTime(1)
    expect(load).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(20_000)
    expect(load).toHaveBeenCalledTimes(3)
  })

  it('never while hidden, and at once when visible again', () => {
    const load = vi.fn()
    renderHook(() => useVisiblePoll(load))
    setVisibility('hidden')
    vi.advanceTimersByTime(60_000)
    expect(load).not.toHaveBeenCalled()
    setVisibility('visible')
    expect(load).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(10_000)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('does not start while the page opens hidden', () => {
    visibility = 'hidden'
    const load = vi.fn()
    renderHook(() => useVisiblePoll(load))
    vi.advanceTimersByTime(30_000)
    expect(load).not.toHaveBeenCalled()
  })

  it('loads at once on focus', () => {
    const load = vi.fn()
    renderHook(() => useVisiblePoll(load))
    window.dispatchEvent(new Event('focus'))
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('stops on unmount', () => {
    const load = vi.fn()
    const { unmount } = renderHook(() => useVisiblePoll(load))
    unmount()
    vi.advanceTimersByTime(30_000)
    window.dispatchEvent(new Event('focus'))
    setVisibility('visible')
    expect(load).not.toHaveBeenCalled()
  })

  it('calls the latest load', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(({ load }) => useVisiblePoll(load), {
      initialProps: { load: first },
    })
    rerender({ load: second })
    vi.advanceTimersByTime(10_000)
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })
})

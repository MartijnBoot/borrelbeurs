/**
 * The player page's refresh (B-05 SD21, AC10): `load` every 10 s while the page
 * is visible, at once when it becomes visible again or regains focus, and
 * never while hidden. A player has no WebSocket.
 */
import { useEffect, useRef } from 'react'

export const POLL_MS = 10_000

export function useVisiblePoll(load: () => void, intervalMs: number = POLL_MS): void {
  const latest = useRef(load)
  useEffect(() => {
    latest.current = load
  })

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null
    const start = () => {
      timer ??= setInterval(() => latest.current(), intervalMs)
    }
    const stop = () => {
      if (timer !== null) clearInterval(timer)
      timer = null
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        latest.current()
        start()
      } else {
        stop()
      }
    }
    const onFocus = () => latest.current()

    if (document.visibilityState === 'visible') start()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onFocus)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onFocus)
    }
  }, [intervalMs])
}

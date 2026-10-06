/**
 * The monotonic clock (`performance.now()`), re-read once a second so the
 * pad's age line and staleness (SD4) move while no message arrives.
 */
import { useEffect, useState } from 'react'

export const NOW_INTERVAL_MS = 1000

export function useNow(): number {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(performance.now()), NOW_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

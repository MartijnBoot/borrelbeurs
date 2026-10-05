/**
 * The running market event, as the board sees it (SD21).
 *
 * An event ends here at its `t_end_ms` on the server's clock -- `Date.now()`
 * plus the skew offset (SD18) -- without waiting for the `end` broadcast
 * (AC30); the timer is re-armed whenever the offset moves. The `end` that
 * follows only removes from the store what is already gone from the board.
 */
import { useEffect, useState } from 'react'
import { selectMarketEvents, useExchange, type MarketEventInfo } from '../exchange'

export type MarketEventKind = MarketEventInfo['kind']

/** True when the kind animates the board: overlay, tiles, faster news. */
export function isAnimated(kind: MarketEventKind | null): kind is 'crash' | 'bubble' {
  return kind === 'crash' || kind === 'bubble'
}

/** The news marquee's playback rate (`koers.html:197-200`: 30 s → 12 s during an event). */
export function newsRate(kind: MarketEventKind | null): number {
  return isAnimated(kind) ? 2.5 : 1
}

/** The running event's kind, or `null`; the most recently started if several overlap. */
export function useActiveMarketEvent(): MarketEventKind | null {
  const events = useExchange(selectMarketEvents)
  const offset = useExchange((s) => s.skewOffsetMs)
  const [ended, setEnded] = useState<ReadonlySet<number>>(() => new Set())

  useEffect(() => {
    const timers = events.map((e) =>
      setTimeout(
        () => setEnded((prev) => new Set(prev).add(e.event_id)),
        Math.max(0, e.t_end_ms - (Date.now() + offset)),
      ),
    )
    return () => timers.forEach(clearTimeout)
  }, [events, offset])

  let active: MarketEventInfo | null = null
  for (const e of events) {
    if (!ended.has(e.event_id) && (active === null || e.t_start_ms > active.t_start_ms)) active = e
  }
  return active?.kind ?? null
}

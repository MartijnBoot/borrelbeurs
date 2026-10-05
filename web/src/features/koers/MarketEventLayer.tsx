/**
 * Market events on the board (SD21, `koers.html:569-594`): per kind, an
 * overlay and a banner over the whole page; the tiles shake or pulse from the
 * kind the page sets on them.
 *
 * - `crash`: overlay, "⚠ MARKTCRASH", tiles shake, news at 2.5×.
 * - `bubble`: overlay, "▲ PRIJSBUBBEL", tiles pulse, news at 2.5×.
 * - `correction`: a calm banner, "Terug naar start" -- no overlay, no
 *   animation (AC31).
 *
 * Which event is running, and when it ends, is `useActiveMarketEvent`'s.
 */
import '../../styles/keyframes.css'
import { isAnimated, type MarketEventKind } from './marketEvent'

const BANNER: Record<MarketEventKind, string> = {
  crash: '⚠ MARKTCRASH',
  bubble: '▲ PRIJSBUBBEL',
  correction: 'Terug naar start',
}

export function MarketEventLayer({ kind }: { kind: MarketEventKind | null }) {
  if (kind === null) return null
  return (
    <>
      {isAnimated(kind) && <div className={`market-overlay ${kind}`} aria-hidden="true" />}
      <div className={`market-banner ${kind}`} role="status">
        {BANNER[kind]}
      </div>
    </>
  )
}

/**
 * Market events on the board (SD21, `koers.html:569-594`): per kind, an
 * overlay and a banner over the whole page; the tiles shake or pulse from the
 * kind the page sets on them.
 *
 * - `crash`: overlay, the warning icon and "MARKTCRASH", tiles shake, news at 2.5×.
 * - `bubble`: overlay, the up-arrow icon and "PRIJSBUBBEL", tiles pulse, news
 *   at 2.5×.
 * - `correction`: a calm banner, "Terug naar start" -- no icon, no overlay, no
 *   animation (AC31).
 *
 * The icons are B-02's pixel icons, white like the banner's text (PD6). A
 * `status` takes no name from its content, so the banner is labelled with its
 * word (PD5).
 *
 * Which event is running, and when it ends, is `useActiveMarketEvent`'s.
 */
import '../../styles/keyframes.css'
import { PixelIcon, type PixelIconName } from '../../components/ui/PixelIcon'
import { isAnimated, type MarketEventKind } from './marketEvent'
import styles from './MarketEventLayer.module.css'

const BANNER: Record<MarketEventKind, { icon?: PixelIconName; text: string }> = {
  crash: { icon: 'warning', text: 'MARKTCRASH' },
  bubble: { icon: 'arrowUp', text: 'PRIJSBUBBEL' },
  correction: { text: 'Terug naar start' },
}

export function MarketEventLayer({ kind }: { kind: MarketEventKind | null }) {
  if (kind === null) return null
  const { icon, text } = BANNER[kind]
  return (
    <>
      {isAnimated(kind) && <div className={`market-overlay ${kind}`} aria-hidden="true" />}
      <div className={`market-banner ${kind}`} role="status" aria-label={text}>
        {icon && <PixelIcon name={icon} className={styles.icon} />}
        {text}
      </div>
    </>
  )
}

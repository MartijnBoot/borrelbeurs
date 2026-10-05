/**
 * The board (`/koers`): the price and news marquees, then a tile per drink in
 * the server's order, keyed by `drink_id`, the clock and v1's legend
 * verbatim, with any market event over the top (SD21). With no live run,
 * SD20's empty state -- inside the shell, so the header, nav and theme still
 * work, and the same page shows the board once a snapshot arrives (AC34).
 */
import { selectEmpty, useExchange } from '../exchange'
import { HeaderClock } from './HeaderClock'
import styles from './KoersPage.module.css'
import { isAnimated, newsRate, useActiveMarketEvent } from './marketEvent'
import { MarketEventLayer } from './MarketEventLayer'
import { NewsMarquee } from './NewsMarquee'
import { PriceMarquee } from './PriceMarquee'
import { Tile } from './Tile'

export function KoersPage() {
  const empty = useExchange(selectEmpty)
  const ids = useExchange((s) => s.drinks.map((d) => d.drink_id).join(','))
  const event = useActiveMarketEvent()

  return (
    <div className={styles.page}>
      {!empty && (
        <>
          <PriceMarquee />
          <NewsMarquee playbackRate={newsRate(event)} />
        </>
      )}
      <div className={styles.container}>
        <div className={styles.board}>
          <div className={styles.bar}>
            <div className={styles.legend}>
              Tegels pulseren bij stijging (rood) of daling (groen).
            </div>
            <HeaderClock />
          </div>
          {empty ? (
            <p className={styles.empty}>Geen actieve borrel</p>
          ) : (
            <div className={styles.tiles} data-market={isAnimated(event) ? event : undefined}>
              {ids === ''
                ? null
                : ids.split(',').map((id) => <Tile key={id} drinkId={Number(id)} />)}
            </div>
          )}
        </div>
      </div>
      {!empty && <MarketEventLayer kind={event} />}
    </div>
  )
}

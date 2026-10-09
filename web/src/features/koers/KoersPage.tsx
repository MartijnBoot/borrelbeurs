/**
 * The board (`/koers`): the price and news marquees, then a tile per active
 * drink (Phase 6 SD18) in the server's order, keyed by `drink_id` -- so a drink
 * removed by `config` loses its tile and the others are not remounted -- then
 * the clock and v1's legend verbatim, with any market event over the top
 * (SD21). With no live run, SD20's empty state -- inside the shell, so the
 * header, nav and theme still work, and the same page shows the board once a
 * snapshot arrives (AC34). Right after a close (Phase 7 PD5) the same calm
 * screen says "Borrel afgelopen" instead, until the next snapshot.
 *
 * While the theme has a promo image (Phase 6 PD9), v1's promo tile sits beside
 * the board and the container takes v1's `has-promo` grid.
 */
import { selectActiveDrinks, selectClosedRun, selectEmpty, useExchange } from '../exchange'
import { HeaderClock } from './HeaderClock'
import styles from './KoersPage.module.css'
import { isAnimated, newsRate, useActiveMarketEvent } from './marketEvent'
import { MarketEventLayer } from './MarketEventLayer'
import { NewsMarquee } from './NewsMarquee'
import { PriceMarquee } from './PriceMarquee'
import { Tile } from './Tile'

export function KoersPage() {
  const empty = useExchange(selectEmpty)
  const closed = useExchange(selectClosedRun)
  const ids = useExchange((s) =>
    selectActiveDrinks(s)
      .map((d) => d.drink_id)
      .join(','),
  )
  const event = useActiveMarketEvent()
  const promo = useExchange((s) => s.theme?.images.promo ?? null)

  return (
    <div className={styles.page}>
      {!empty && (
        <>
          <PriceMarquee />
          <NewsMarquee playbackRate={newsRate(event)} />
        </>
      )}
      <div className={promo === null ? styles.container : `${styles.container} has-promo`}>
        <div className={styles.board}>
          <div className={styles.bar}>
            <div className={styles.legend}>
              Tegels pulseren bij stijging (rood) of daling (groen).
            </div>
            <HeaderClock />
          </div>
          {empty ? (
            <p className={styles.empty}>
              {closed === null ? 'Geen actieve borrel' : 'Borrel afgelopen'}
            </p>
          ) : (
            <div className={styles.tiles} data-market={isAnimated(event) ? event : undefined}>
              {ids === ''
                ? null
                : ids.split(',').map((id) => <Tile key={id} drinkId={Number(id)} />)}
            </div>
          )}
        </div>
        {promo !== null && (
          <div className={styles.promo}>
            <img src={promo} alt="Promotie" />
          </div>
        )}
      </div>
      {!empty && <MarketEventLayer kind={event} />}
    </div>
  )
}

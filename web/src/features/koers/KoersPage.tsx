/**
 * The board (`/koers`): a tile per drink in the server's order, keyed by
 * `drink_id`, the clock and v1's legend verbatim. With no live run, SD20's
 * empty state -- inside the shell, so the header, nav and theme still work,
 * and the same page shows the tiles once a snapshot arrives (AC34).
 */
import { selectEmpty, useExchange } from '../exchange'
import { HeaderClock } from './HeaderClock'
import styles from './KoersPage.module.css'
import { Tile } from './Tile'

export function KoersPage() {
  const empty = useExchange(selectEmpty)
  const ids = useExchange((s) => s.drinks.map((d) => d.drink_id).join(','))

  return (
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
          <div className={styles.tiles}>
            {ids === '' ? null : ids.split(',').map((id) => <Tile key={id} drinkId={Number(id)} />)}
          </div>
        )}
      </div>
    </div>
  )
}

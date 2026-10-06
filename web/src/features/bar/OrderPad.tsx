/**
 * The order pad (Phase 5 SD5, SD11, SD18): one "+1" button per drink, in the
 * store's drink order, priced from the controller's **displayed** quote.
 *
 * A pointer down or an Enter/Space keydown starts a press, and pointer up,
 * cancel, leave or keyup ends it; `click` is the tap (PD10). The press starts
 * before `click`, so the tap reads a quote that is already held. The pad never
 * reads a price from the store -- only through the controller's `Quote`.
 *
 * Above `AGE_SHOW_MS` the age line and "Ververs" show (AC7); when the latest
 * quote is stale every button is disabled (AC8), as it is while a conflict
 * is open (AC14). Socket state plays no part (SD11).
 */
import type { KeyboardEvent } from 'react'
import { Button } from '../../components/ui/Button'
import { formatEuro } from '../../lib/format'
import { selectDrinks, useExchange } from '../exchange'
import { ageMs, isStale, showAge } from './model/holdBuffer'
import type { BarView } from './model/barController'
import type { BarActions } from './useBarController'
import { useNow } from './useNow'
import styles from './OrderPad.module.css'

export interface OrderPadProps {
  view: BarView
  actions: Pick<BarActions, 'press' | 'release' | 'tap' | 'refresh'>
}

const PRESS_KEYS = new Set(['Enter', ' '])
/** The keyboard is one press; fingers are told apart by pointer id (AC5). */
const KEY_PRESS = 'key'

export function OrderPad({ view, actions }: OrderPadProps) {
  const drinks = useExchange(selectDrinks)
  const now = useNow()
  const { displayed, latest, entries, headConflict } = view
  const stale = isStale(latest, now)
  const disabled = stale || headConflict !== null

  const onKeyDown = (event: KeyboardEvent) => {
    if (PRESS_KEYS.has(event.key)) actions.press(KEY_PRESS)
  }
  const onKeyUp = (event: KeyboardEvent) => {
    if (PRESS_KEYS.has(event.key)) actions.release(KEY_PRESS)
  }

  return (
    <div className={styles.pad} data-quote-version={displayed?.version}>
      <div className={styles.grid}>
        {drinks.map(({ drink_id, name }) => {
          const price = displayed?.prices[drink_id]
          return (
            <Button
              key={drink_id}
              className={styles.drink}
              disabled={disabled || price === undefined}
              onPointerDown={(e) => actions.press(e.pointerId)}
              onPointerUp={(e) => actions.release(e.pointerId)}
              onPointerCancel={(e) => actions.release(e.pointerId)}
              onPointerLeave={(e) => actions.release(e.pointerId)}
              onKeyDown={onKeyDown}
              onKeyUp={onKeyUp}
              onClick={() => actions.tap(drink_id)}
            >
              +1 {name} — {price === undefined ? '—' : formatEuro(price)}
            </Button>
          )
        })}
      </div>
      {stale && <p className={styles.stale}>Geen actuele prijzen — wacht op verbinding</p>}
      {displayed !== null && showAge(displayed, now) && (
        <p className={styles.age}>
          Prijzen van {Math.floor(ageMs(displayed, now) / 1000)} s geleden{' '}
          <Button onClick={actions.refresh}>Ververs</Button>
        </p>
      )}
      {entries.length === 0 && <p className={styles.status}>Klaar</p>}
    </div>
  )
}

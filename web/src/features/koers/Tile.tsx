/**
 * One drink's tile (`koers.html:455-468`): the name as a text node -- never
 * HTML (AC32) -- the price, the delta, and its chart keyed by `drink_id`.
 *
 * SD23's pulse: `rising` or `falling` when the displayed price changed in
 * that direction, nothing after a snapshot. The pulse is an animation; when
 * it ends, that change is marked shown, so the next change pulses again.
 */
import { useState } from 'react'
import { deltaParts, formatEuro } from '../../lib/format'
import { pulseDirection, useExchange, type DrinkId } from '../exchange'
import { DeltaIcon } from './DeltaIcon'
import styles from './KoersPage.module.css'
import { DrinkChart } from './ui/DrinkChart'

export function Tile({ drinkId }: { drinkId: DrinkId }) {
  const name = useExchange((s) => s.drinks.find((d) => d.drink_id === drinkId)?.name ?? '')
  const price = useExchange((s) => s.prices[drinkId]?.price_cents)
  const previous = useExchange((s) => s.prevPriceCents[drinkId])
  const direction = useExchange((s) => pulseDirection(s, drinkId))
  const change = `${previous}->${price}`
  const [shown, setShown] = useState<string | null>(null)
  const pulse = direction !== null && shown !== change ? direction : undefined
  const delta =
    price === undefined || previous === undefined
      ? { direction: null, text: '—' }
      : deltaParts(previous, price)

  return (
    <div
      className={styles.tile}
      data-pulse={pulse}
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) setShown(change)
      }}
    >
      <div className={styles.name}>{name}</div>
      <div className={styles.price}>{price === undefined ? '—' : formatEuro(price)}</div>
      <div className={styles.change}>
        <DeltaIcon direction={delta.direction} />
        {delta.text}
      </div>
      <div className={styles.spark}>
        <DrinkChart drinkId={drinkId} />
      </div>
    </div>
  )
}

/**
 * The pending-orders list (Phase 5 SD8, SD10; PD7 lifetimes live in the
 * intents). One line per intent, in tap order. An accepted order shows the
 * **receipt's** price (AC3). Pending entries never touch the store or the
 * totals: revenue moves only on the server's `order` message (SD10).
 */
import { Button } from '../../components/ui/Button'
import { formatEuro } from '../../lib/format'
import { selectDrinks, useExchange } from '../exchange'
import type { BarView } from './model/barController'
import type { OrderEntry } from './model/orderIntents'
import type { BarActions } from './useBarController'
import styles from './PendingOrders.module.css'

export interface PendingOrdersProps {
  view: Pick<BarView, 'entries'>
  actions: Pick<BarActions, 'retry' | 'dismiss'>
}

export function PendingOrders({ view, actions }: PendingOrdersProps) {
  const drinks = useExchange(selectDrinks)
  if (view.entries.length === 0) return null
  const nameOf = (id: number) => drinks.find((d) => d.drink_id === id)?.name ?? `#${id}`
  return (
    <ul className={styles.list}>
      {view.entries.map((entry) => (
        <li key={entry.id} className={`${styles.entry} ${styles[entry.state] ?? ''}`}>
          <Line entry={entry} name={nameOf(entry.drinkId)} actions={actions} />
        </li>
      ))}
    </ul>
  )
}

function Line({
  entry,
  name,
  actions,
}: {
  entry: OrderEntry
  name: string
  actions: PendingOrdersProps['actions']
}) {
  switch (entry.state) {
    case 'sending':
    case 'conflict':
      return <>1× {name} — bezig…</>
    case 'accepted':
      return (
        <>
          1× {name} besteld —{' '}
          {entry.unitPriceCents === null ? '—' : formatEuro(entry.unitPriceCents)}
        </>
      )
    case 'unknown':
      return (
        <>
          <strong>Onbekend</strong>
          <span>{name}: niet bevestigd — opnieuw proberen?</span>
          <Button onClick={() => actions.retry(entry.id)}>Opnieuw</Button>
          <Button onClick={() => actions.dismiss(entry.id)}>Sluiten</Button>
        </>
      )
    case 'failed':
      return <>{name}: Fout bij bestellen</>
    case 'unavailable':
      return <>{name} is niet meer beschikbaar</>
    case 'cancelled':
      return <>{name}: Geannuleerd</>
    case 'dismissed':
      return <>Mogelijk toch geboekt — controleer de omzet</>
  }
}

/**
 * The pending-orders list (Phase 5 SD8, SD10; PD7 lifetimes live in the
 * intents). One line per intent, in tap order, naming its basket's lines
 * ("2× Bier, 1× Wijn", B-06 SD7). An accepted order shows the **receipt's**
 * total (AC3). Pending entries never touch the store or the totals: revenue
 * moves only on the server's `order` message (SD10).
 */
import { Button } from '../../components/ui/Button'
import { formatEuro } from '../../lib/format'
import { selectDrinks, useExchange } from '../exchange'
import { linesText } from './model/basket'
import type { BarView } from './model/barController'
import type { OrderEntry, Refusal } from './model/orderIntents'
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
          <Line entry={entry} name={linesText(entry.lines, nameOf)} actions={actions} />
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
      return <>{name} — bezig…</>
    case 'accepted':
      return (
        <>
          {name} besteld — {entry.receipt === null ? '—' : formatEuro(entry.receipt.total_cents)}
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
      return <>{name}: niet meer beschikbaar</>
    case 'cancelled':
      return <>{name}: Geannuleerd</>
    case 'dismissed':
      return <>Mogelijk toch geboekt — controleer de omzet</>
    case 'refused':
      return <>{refusalText(entry.refusal)}</>
  }
}

/** The server's wallet refusals, as the bar says them (B-06 SD15, PD18). */
function refusalText(refusal: Refusal | null): string {
  switch (refusal?.code) {
    case 'wallet_required':
      return 'Scan eerst een wallet'
    case 'wallet_not_found':
      return 'Onbekende wallet'
    default:
      return 'Fout bij bestellen'
  }
}

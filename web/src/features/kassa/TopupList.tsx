/**
 * A found wallet's top-ups, newest first (B-05 SD12, SD22): the amount, when,
 * which key booked it, and whether it was reversed.
 */
import { formatEuro } from '../../lib/format'
import { formatDayMonthTime } from '../../lib/time'
import type { Topup } from './api'
import styles from './KassaPage.module.css'

export function TopupList({ topups }: { topups: readonly Topup[] }) {
  if (topups.length === 0) return <p className={styles.muted}>Nog geen opwaarderingen</p>
  return (
    <ul className={styles.topups} aria-label="Opwaarderingen">
      {topups.map((topup) => (
        <li key={topup.entry_id} className={topup.reversed ? styles.reversed : undefined}>
          <span className={styles.money}>{formatEuro(topup.amount_cents)}</span>
          <span>{formatDayMonthTime(Date.parse(topup.created_at))}</span>
          <span className={styles.muted}>{topup.actor_label ?? ''}</span>
          {topup.reversed && <span className={styles.muted}>teruggedraaid</span>}
        </li>
      ))}
    </ul>
  )
}

/**
 * A found wallet's top-ups, newest first (B-05 SD12, SD22): the amount, when,
 * which key booked it, and whether it was reversed. Each top-up not yet
 * reversed has "Terugdraaien" behind a confirm, sent under a fresh key; the
 * server's refusals show in Dutch (AC21, AC22).
 */
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { newIdempotencyKey } from '../../lib/idempotencyKey'
import { formatDayMonthTime } from '../../lib/time'
import { reverse, type Topup } from './api'
import { refusalText } from './errors'
import styles from './KassaPage.module.css'

export function TopupList({
  topups,
  onReversed,
}: {
  topups: readonly Topup[]
  onReversed: () => void
}) {
  const [confirming, setConfirming] = useState<Topup | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function send(topup: Topup) {
    setConfirming(null)
    setError(null)
    try {
      await reverse(topup.entry_id, newIdempotencyKey())
      onReversed()
    } catch (failure) {
      setError(refusalText(failure))
    }
  }

  if (topups.length === 0) return <p className={styles.muted}>Nog geen opwaarderingen</p>
  return (
    <>
      <ul className={styles.topups} aria-label="Opwaarderingen">
        {topups.map((topup) => (
          <li key={topup.entry_id} className={topup.reversed ? styles.reversed : undefined}>
            <span className={styles.money}>{formatEuro(topup.amount_cents)}</span>
            <span>{formatDayMonthTime(Date.parse(topup.created_at))}</span>
            <span className={styles.muted}>{topup.actor_label ?? ''}</span>
            {topup.reversed ? (
              <span className={styles.muted}>teruggedraaid</span>
            ) : (
              <Button onClick={() => setConfirming(topup)}>Terugdraaien</Button>
            )}
          </li>
        ))}
      </ul>
      {error !== null && (
        <div className={styles.err} role="alert">
          {error}
        </div>
      )}
      <ConfirmDialog
        open={confirming !== null}
        message={
          confirming === null
            ? ''
            : `${formatEuro(confirming.amount_cents)} van ` +
              `${formatDayMonthTime(Date.parse(confirming.created_at))} terugdraaien?`
        }
        confirmLabel="Terugdraaien"
        cancelLabel="Annuleren"
        onConfirm={() => confirming !== null && void send(confirming)}
        onCancel={() => setConfirming(null)}
      />
    </>
  )
}

/**
 * A found wallet's payments at the bar, newest first, at any age (B-06 SD9,
 * AC23): the order's lines ("Bestelling niet meer beschikbaar" once its run is
 * deleted, AC24), the amount, when, and which key booked it. Each payment not
 * yet refunded has "Terugboeken" behind a confirm, sent under a fresh key; the
 * server's refusals show in Dutch (PD18). A refund returns the money only: the
 * order and the revenue stay (SD9).
 */
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { newIdempotencyKey } from '../../lib/idempotencyKey'
import { formatDayMonthTime } from '../../lib/time'
import { type Payment, refund } from './api'
import { refusalText } from './errors'
import styles from './KassaPage.module.css'

function linesOf(payment: Payment): string {
  if (payment.lines === null) return 'Bestelling niet meer beschikbaar'
  return payment.lines.map((line) => `${line.qty}× ${line.name}`).join(', ')
}

export function PaymentList({
  walletName,
  payments,
  onRefunded,
}: {
  walletName: string
  payments: readonly Payment[]
  onRefunded: () => void
}) {
  const [confirming, setConfirming] = useState<Payment | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function send(payment: Payment) {
    setConfirming(null)
    setError(null)
    try {
      await refund(payment.entry_id, newIdempotencyKey())
      onRefunded()
    } catch (failure) {
      setError(refusalText(failure))
    }
  }

  return (
    <>
      <h3>Betalingen</h3>
      {payments.length === 0 ? (
        <p className={styles.muted}>Nog geen betalingen</p>
      ) : (
        <ul className={styles.topups} aria-label="Betalingen">
          {payments.map((payment) => (
            <li key={payment.entry_id} className={payment.refunded ? styles.reversed : undefined}>
              <span>
                {linesOf(payment)} —{' '}
                <span className={styles.money}>{formatEuro(payment.amount_cents)}</span> op{' '}
                {formatDayMonthTime(Date.parse(payment.created_at))}, {payment.actor_label ?? ''}
              </span>
              {payment.refunded ? (
                <span className={styles.muted}>teruggeboekt</span>
              ) : (
                <Button onClick={() => setConfirming(payment)}>Terugboeken</Button>
              )}
            </li>
          ))}
        </ul>
      )}
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
            : `${formatEuro(confirming.amount_cents)} terugboeken naar ${walletName}?`
        }
        confirmLabel="Terugboeken"
        cancelLabel="Annuleren"
        onConfirm={() => confirming !== null && void send(confirming)}
        onCancel={() => setConfirming(null)}
      />
    </>
  )
}

/**
 * The payments this bar key booked in the last 10 minutes (B-06 SD9; AC20-AC22):
 * each with its lines, amount, time and wallet name ("verwijderde wallet" once
 * deleted), and "Terugboeken" behind a confirm, or "teruggeboekt".
 *
 * The list is the server's: fetched on mount, when a newer paid order is
 * accepted (`lastPaid`, the newest such entry's id), after a refund, and every
 * `PAYMENTS_REFRESH_MS`. The page never filters by its own clock (PD16): a
 * payment shown past its window answers 403 `refund_not_allowed`.
 *
 * One `Idempotency-Key` per confirmed refund. A network failure keeps it, and
 * "Opnieuw" resends under the same key, so a refund that reached the server is
 * a replay, not booked twice (B-05 /review C1). Until it has an answer, no other
 * refund starts.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { HttpError } from '../../lib/http'
import { newIdempotencyKey } from '../../lib/idempotencyKey'
import { formatHourMinute } from '../../lib/time'
import { type BarPayment, recentPayments, refund } from './api/wallets'
import { PAYMENTS_REFRESH_MS } from './model/constants'
import styles from './RecentPayments.module.css'

const TITLE = 'Betalingen (laatste 10 minuten)'
const NETWORK = 'Verbindingsfout. Probeer opnieuw.'
const REFUSALS: Readonly<Record<string, string>> = {
  already_refunded: 'Deze betaling is al teruggeboekt.',
  refund_not_allowed: 'Terugboeken kan hier alleen binnen 10 minuten na de betaling.',
  wallet_deleted: 'Deze wallet bestaat niet meer.',
}

interface Intent {
  payment: BarPayment
  key: string
}

const nameOf = (payment: BarPayment) => payment.name ?? 'verwijderde wallet'

function linesOf(payment: BarPayment): string {
  if (payment.lines === null) return 'Bestelling niet meer beschikbaar'
  return payment.lines.map((line) => `${line.qty}× ${line.name}`).join(', ')
}

export function RecentPayments({
  lastPaid,
  onRefunded,
}: {
  lastPaid: number
  /** A refund was booked: the page looks the held wallet's balance up again (AC18). */
  onRefunded?: () => void
}) {
  const [payments, setPayments] = useState<BarPayment[] | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [confirming, setConfirming] = useState<BarPayment | null>(null)
  const [failed, setFailed] = useState<Intent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const seenPaid = useRef(lastPaid)

  const load = useCallback(
    () =>
      recentPayments().then(
        (list) => {
          setPayments(list)
          setLoadFailed(false)
        },
        () => setLoadFailed(true),
      ),
    [],
  )

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), PAYMENTS_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => {
    if (lastPaid <= seenPaid.current) return
    seenPaid.current = lastPaid
    void load()
  }, [lastPaid, load])

  async function send(intent: Intent) {
    setBusy(true)
    setError(null)
    setFailed(null)
    try {
      await refund(intent.payment.entry_id, intent.key)
      onRefunded?.()
      await load()
    } catch (failure) {
      const text = (failure instanceof HttpError && REFUSALS[failure.code]) || NETWORK
      // Only a request that got no answer may have been booked: that one is retried.
      if (!(failure instanceof HttpError)) setFailed(intent)
      setError(text)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={styles.section} aria-label={TITLE}>
      <h3 className={styles.title}>{TITLE}</h3>
      {payments === null ? (
        <p className={styles.muted}>{loadFailed ? NETWORK : 'Laden…'}</p>
      ) : payments.length === 0 ? (
        <p className={styles.muted}>Nog geen betalingen</p>
      ) : (
        <ul className={styles.list}>
          {payments.map((payment) => (
            <li key={payment.entry_id} className={styles.row}>
              <span>
                {linesOf(payment)} — {formatEuro(payment.amount_cents)} om{' '}
                {formatHourMinute(Date.parse(payment.created_at))}, {nameOf(payment)}
              </span>
              {payment.refunded ? (
                <span className={styles.muted}>teruggeboekt</span>
              ) : (
                <Button disabled={busy || failed !== null} onClick={() => setConfirming(payment)}>
                  Terugboeken
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error !== null && (
        <div className={styles.error}>
          <span role="alert">{error}</span>
          {failed !== null && (
            <Button disabled={busy} onClick={() => void send(failed)}>
              Opnieuw
            </Button>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirming !== null}
        message={
          confirming === null
            ? ''
            : `${formatEuro(confirming.amount_cents)} terugboeken naar ${nameOf(confirming)}?`
        }
        confirmLabel="Terugboeken"
        cancelLabel="Annuleren"
        onConfirm={() => {
          if (confirming === null) return
          setConfirming(null)
          void send({ payment: confirming, key: newIdempotencyKey() })
        }}
        onCancel={() => setConfirming(null)}
      />
    </section>
  )
}

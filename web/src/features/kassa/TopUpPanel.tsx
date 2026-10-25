/**
 * Top up (B-05 SD10; AC15-AC18): €10 to €100 in €5 steps, starting at €10, then
 * "Opwaarderen" behind a confirm. A top-up in the last 2 minutes changes the
 * question, never the answer: the kassa may still book it (SD10).
 *
 * One `Idempotency-Key` per confirmed intent. A network failure keeps the
 * intent, and "Opnieuw" resends it under the same key, so a request that did
 * reach the server is answered as a replay, not booked twice (AC18).
 */
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { newIdempotencyKey } from '../../lib/idempotencyKey'
import { formatHourMinute } from '../../lib/time'
import { type KassaWallet, topUp } from './api'
import { NETWORK, refusalText } from './errors'
import styles from './KassaPage.module.css'

export const MIN_CENTS = 1_000
export const MAX_CENTS = 10_000
export const STEP_CENTS = 500

interface Intent {
  amountCents: number
  key: string
}

function question(wallet: KassaWallet, amountCents: number): [string, string] {
  const recent = wallet.recent_topup
  if (recent === null) {
    return [`${formatEuro(amountCents)} opwaarderen voor ${wallet.name}?`, 'Opwaarderen']
  }
  const at = formatHourMinute(Date.parse(recent.at))
  return [
    `${wallet.name} is om ${at} al opgewaardeerd met ${formatEuro(recent.amount_cents)}.` +
      ` Nog een keer ${formatEuro(amountCents)}?`,
    'Ja, nog een keer',
  ]
}

export function TopUpPanel({ wallet, onBooked }: { wallet: KassaWallet; onBooked: () => void }) {
  const [amountCents, setAmountCents] = useState(MIN_CENTS)
  const [confirming, setConfirming] = useState(false)
  const [failed, setFailed] = useState<Intent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function send(intent: Intent) {
    setBusy(true)
    setError(null)
    setFailed(null)
    try {
      await topUp(wallet.wallet_id, intent.amountCents, intent.key)
      onBooked()
    } catch (failure) {
      const text = refusalText(failure)
      // Only a request that got no answer may have been booked: that one is retried.
      if (text === NETWORK) setFailed(intent)
      setError(text)
    } finally {
      setBusy(false)
    }
  }

  const [message, confirmLabel] = question(wallet, amountCents)
  return (
    <section className={styles.panel} aria-label="Opwaarderen">
      <div className={styles.stepper}>
        <Button
          aria-label="€ 5 minder"
          disabled={busy || amountCents <= MIN_CENTS}
          onClick={() => setAmountCents((cents) => Math.max(MIN_CENTS, cents - STEP_CENTS))}
        >
          −
        </Button>
        <output className={styles.amount} aria-label="Bedrag">
          {formatEuro(amountCents)}
        </output>
        <Button
          aria-label="€ 5 meer"
          disabled={busy || amountCents >= MAX_CENTS}
          onClick={() => setAmountCents((cents) => Math.min(MAX_CENTS, cents + STEP_CENTS))}
        >
          +
        </Button>
      </div>
      <button
        type="button"
        className={styles.primary}
        disabled={busy}
        onClick={() => setConfirming(true)}
      >
        Opwaarderen
      </button>
      {error !== null && (
        <div className={styles.err} role="alert">
          {error}
          {failed !== null && (
            <Button disabled={busy} onClick={() => void send(failed)}>
              Opnieuw
            </Button>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        message={message}
        confirmLabel={confirmLabel}
        cancelLabel="Annuleren"
        onConfirm={() => {
          setConfirming(false)
          void send({ amountCents, key: newIdempotencyKey() })
        }}
        onCancel={() => setConfirming(false)}
      />
    </section>
  )
}

/**
 * Top up (B-05 SD10; AC15-AC18): €10 to €100 in €5 steps, starting at €10, then
 * "Opwaarderen" behind a confirm. A top-up in the last 2 minutes changes the
 * question, never the answer: the kassa may still book it (SD10). The wallet is
 * looked up again before it asks, so a top-up from another kassa since the
 * lookup is in the question, and an old one has left it (/review R2).
 *
 * One `Idempotency-Key` per confirmed intent. A network failure keeps the
 * intent, and "Opnieuw" resends it under the same key, so a request that did
 * reach the server is answered as a replay, not booked twice (AC18). Until it
 * has an answer, "Opwaarderen" is off; opening another wallet and coming back
 * looks this one up afresh, warning included.
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

export function TopUpPanel({
  wallet,
  onBooked,
  refresh,
}: {
  wallet: KassaWallet
  onBooked: () => void
  refresh: () => Promise<KassaWallet>
}) {
  const [amountCents, setAmountCents] = useState(MIN_CENTS)
  // The wallet as looked up just before the confirm opened; null while closed.
  const [asked, setAsked] = useState<KassaWallet | null>(null)
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

  async function ask() {
    setBusy(true)
    setError(null)
    try {
      setAsked(await refresh())
    } catch (failure) {
      // Nothing was sent, so nothing waits for "Opnieuw".
      setError(refusalText(failure))
    } finally {
      setBusy(false)
    }
  }

  const [message, confirmLabel] = question(asked ?? wallet, amountCents)
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
        // Not while an intent awaits "Opnieuw": it may have been booked, and a
        // fresh key under the 2-minute warning from before it would book it twice.
        disabled={busy || failed !== null}
        onClick={() => void ask()}
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
        open={asked !== null}
        message={message}
        confirmLabel={confirmLabel}
        cancelLabel="Annuleren"
        onConfirm={() => {
          setAsked(null)
          void send({ amountCents, key: newIdempotencyKey() })
        }}
        onCancel={() => setAsked(null)}
      />
    </section>
  )
}

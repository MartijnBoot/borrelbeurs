/**
 * "Saldo overzetten van…" (B-05 SD11; AC25-AC27): a player on a new phone has a
 * new, empty wallet open; the kassa finds the old one by name (or its short
 * code) and moves its whole balance and its name onto the open one. The old
 * wallet is deleted by the move.
 *
 * Each match shows its name, sign-up date, balance and last top-up, so two
 * players with similar names can be told apart. The open wallet is never
 * offered. The confirm names both wallets.
 */
import { type FormEvent, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import { formatEuro } from '../../lib/format'
import { newIdempotencyKey } from '../../lib/idempotencyKey'
import { formatDayMonth, formatDayMonthTime } from '../../lib/time'
import { type FoundWallet, type KassaWallet, move, searchWallets } from './api'
import { refusalText } from './errors'
import styles from './KassaPage.module.css'

function moveQuestion(source: FoundWallet, target: KassaWallet): string {
  const created = formatDayMonth(Date.parse(source.created_at))
  return (
    `${formatEuro(source.balance_cents)} en de naam '${source.name}' van ${source.name}` +
    ` (aangemaakt ${created}) naar ${target.name} overzetten?`
  )
}

export function MoveDialog({
  target,
  onMoved,
  onClose,
}: {
  target: KassaWallet
  onMoved: () => void
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [matches, setMatches] = useState<FoundWallet[] | null>(null)
  const [choice, setChoice] = useState<FoundWallet | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function search(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      const found = await searchWallets(text)
      setMatches(found.filter((wallet) => wallet.wallet_id !== target.wallet_id))
    } catch (failure) {
      setError(refusalText(failure))
    } finally {
      setBusy(false)
    }
  }

  async function confirm(source: FoundWallet) {
    setChoice(null)
    setBusy(true)
    setError(null)
    try {
      await move(target.wallet_id, source.wallet_id, newIdempotencyKey())
      onMoved()
    } catch (failure) {
      setError(refusalText(failure))
      setBusy(false)
    }
  }

  return (
    <section className={styles.move} aria-label="Saldo overzetten">
      <form className={styles.find} onSubmit={search}>
        <Field id="move-name" label="Naam of code van de oude wallet">
          <input
            id="move-name"
            type="text"
            autoComplete="off"
            maxLength={40}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <div className={styles.actions}>
          <button type="submit" className={styles.primary} disabled={busy}>
            Zoeken
          </button>
          <Button onClick={onClose}>Annuleren</Button>
        </div>
      </form>
      {matches !== null && matches.length === 0 && (
        <p className={styles.muted}>Geen andere wallet gevonden</p>
      )}
      {matches !== null && matches.length > 0 && (
        <ul className={styles.matches} aria-label="Gevonden wallets">
          {matches.map((wallet) => (
            <li key={wallet.wallet_id}>
              <button type="button" disabled={busy} onClick={() => setChoice(wallet)}>
                <strong>{wallet.name}</strong>
                <span>aangemaakt {formatDayMonth(Date.parse(wallet.created_at))}</span>
                <span>{formatEuro(wallet.balance_cents)}</span>
                <span>
                  {wallet.last_topup_at === null
                    ? 'nog niet opgewaardeerd'
                    : `opgewaardeerd ${formatDayMonthTime(Date.parse(wallet.last_topup_at))}`}
                </span>
              </button>
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
        open={choice !== null}
        message={choice === null ? '' : moveQuestion(choice, target)}
        confirmLabel="Overzetten"
        cancelLabel="Annuleren"
        onConfirm={() => choice !== null && void confirm(choice)}
        onCancel={() => setChoice(null)}
      />
    </section>
  )
}

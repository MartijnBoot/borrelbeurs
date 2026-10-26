/**
 * Wallets (B-05 SD6, SD15, SD16; AC30, AC33, AC34), admin only:
 *
 * - **Aanmeldcode:** change or clear the sign-up code. Set, it shows the
 *   poster's link `<origin>/speler?code=<code>` (PD20); cleared, sign-up is
 *   closed.
 * - **Bewaartermijnen:** the two retention periods, whole days and months.
 * - **Totalen:** "Tegoed", what the association still owes in drinks, and
 *   "Rood", what players owe, never netted (B-06 SD20, PD10); per borrel the
 *   top-ups net of reversals and the wallet payments net of refunds, newest
 *   first, with "Zonder borrel" for those booked when none was live (PD2).
 * - **The list:** each wallet's name, balance and last activity, with
 *   "Verwijderen" behind a confirm naming the balance that is lost, or the
 *   debt that is written off (B-06 SD8, PD18).
 */
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { formatBalance, formatEuro } from '../../lib/format'
import { HttpError } from '../../lib/http'
import { formatDayMonth } from '../../lib/time'
import {
  deleteWallet,
  getOverview,
  getSettings,
  type ListedWallet,
  type Overview,
  putSettings,
  type WalletSettings,
} from './api'
import styles from './WalletsSection.module.css'

const NETWORK = 'Verbindingsfout. Probeer opnieuw.'
const PERIODS = 'Kies 1–365 dagen en 1–60 maanden.'

function deleteQuestion(wallet: ListedWallet): string {
  const question = `Wallet '${wallet.name}' verwijderen?`
  return wallet.balance_cents < 0
    ? `${question} De schuld van ${formatEuro(-wallet.balance_cents)} vervalt.`
    : `${question} Het saldo van ${formatEuro(wallet.balance_cents)} vervalt.`
}

function signupLink(code: string): string {
  return `${window.location.origin}/speler?code=${encodeURIComponent(code)}`
}

export function WalletsSection() {
  const [settings, setSettings] = useState<WalletSettings | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [failed, setFailed] = useState(false)
  const [code, setCode] = useState('')
  const [days, setDays] = useState('')
  const [months, setMonths] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const [periodError, setPeriodError] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<ListedWallet | null>(null)
  const [busy, setBusy] = useState(false)

  const show = useCallback((stored: WalletSettings) => {
    setSettings(stored)
    setCode(stored.signup_code ?? '')
    setDays(String(stored.unfunded_days))
    setMonths(String(stored.inactive_months))
  }, [])

  const reload = useCallback(
    () =>
      Promise.all([getSettings(), getOverview()]).then(
        ([stored, read]) => {
          show(stored)
          setOverview(read)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [show],
  )

  useEffect(() => {
    void reload()
  }, [reload])

  async function save(next: WalletSettings, onError: (text: string) => void) {
    setBusy(true)
    try {
      show(await putSettings(next))
      setCodeError(null)
      setPeriodError(null)
    } catch (failure) {
      onError(failure instanceof HttpError && failure.status === 422 ? PERIODS : NETWORK)
    } finally {
      setBusy(false)
    }
  }

  function saveCode(event: FormEvent, signupCode: string | null) {
    event.preventDefault()
    if (settings === null) return
    void save({ ...settings, signup_code: signupCode }, (text) =>
      setCodeError(text === PERIODS ? 'Kies een code van hoogstens 40 tekens.' : text),
    )
  }

  function savePeriods(event: FormEvent) {
    event.preventDefault()
    if (settings === null) return
    void save(
      { ...settings, unfunded_days: Number(days), inactive_months: Number(months) },
      setPeriodError,
    )
  }

  async function remove(wallet: ListedWallet) {
    setDeleting(null)
    setBusy(true)
    try {
      await deleteWallet(wallet.wallet_id)
      setListError(null)
      await reload()
    } catch {
      setListError(NETWORK)
    } finally {
      setBusy(false)
    }
  }

  if (settings === null || overview === null) {
    return <p className={styles.muted}>{failed ? NETWORK : 'Laden…'}</p>
  }
  return (
    <>
      <section className={styles.subsection} aria-label="Aanmeldcode">
        <h3>Aanmeldcode</h3>
        <form className={styles.row} onSubmit={(event) => saveCode(event, code)}>
          <Field id="wallets-code" label="Aanmeldcode">
            <input
              id="wallets-code"
              className={fieldStyles.input}
              value={code}
              maxLength={40}
              onChange={(event) => setCode(event.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy}>
            Opslaan
          </Button>
          <Button disabled={busy} onClick={(event) => saveCode(event, null)}>
            Wissen
          </Button>
        </form>
        {settings.signup_code === null ? (
          <p className={styles.muted}>Aanmelden is gesloten.</p>
        ) : (
          <p className={styles.link}>{signupLink(settings.signup_code)}</p>
        )}
        {codeError !== null && (
          <p className={styles.error} role="alert">
            {codeError}
          </p>
        )}
      </section>

      <section className={styles.subsection} aria-label="Bewaartermijnen">
        <h3>Bewaartermijnen</h3>
        <form className={styles.row} onSubmit={savePeriods} noValidate>
          <Field id="wallets-days" label="Zonder opwaardering verwijderen na (dagen)">
            <input
              id="wallets-days"
              className={fieldStyles.input}
              type="number"
              inputMode="numeric"
              min={1}
              max={365}
              step={1}
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
          </Field>
          <Field id="wallets-months" label="Inactief verwijderen na (maanden)">
            <input
              id="wallets-months"
              className={fieldStyles.input}
              type="number"
              inputMode="numeric"
              min={1}
              max={60}
              step={1}
              value={months}
              onChange={(event) => setMonths(event.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy}>
            Opslaan
          </Button>
        </form>
        {periodError !== null && (
          <p className={styles.error} role="alert">
            {periodError}
          </p>
        )}
      </section>

      <section className={styles.subsection} aria-label="Totalen">
        <h3>Totalen</h3>
        <p>Tegoed: {formatEuro(overview.positive_balance_cents)}</p>
        <p>Rood: {formatBalance(overview.negative_balance_cents)}</p>
        {overview.per_borrel.length > 0 && (
          <ul className={styles.list} aria-label="Per borrel">
            {overview.per_borrel.map((row) => (
              <li key={row.run_id ?? 'zonder'}>
                {row.name ?? 'Zonder borrel'}: opgewaardeerd {formatEuro(row.net_topup_cents)},
                besteed {formatEuro(row.net_payment_cents)}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.subsection} aria-label="Alle wallets">
        <h3>Alle wallets</h3>
        {overview.wallets.length === 0 ? (
          <p className={styles.muted}>Nog geen wallets</p>
        ) : (
          <ul className={styles.list}>
            {overview.wallets.map((wallet) => (
              <li key={wallet.wallet_id} className={styles.wallet}>
                <strong>{wallet.name}</strong>
                <span>{formatBalance(wallet.balance_cents)}</span>
                <span className={styles.muted}>
                  laatst actief {formatDayMonth(Date.parse(wallet.last_activity_at))}
                </span>
                <Button disabled={busy} onClick={() => setDeleting(wallet)}>
                  Verwijderen
                </Button>
              </li>
            ))}
          </ul>
        )}
        {listError !== null && (
          <p className={styles.error} role="alert">
            {listError}
          </p>
        )}
      </section>

      <ConfirmDialog
        open={deleting !== null}
        message={deleting === null ? '' : deleteQuestion(deleting)}
        confirmLabel="Verwijderen"
        cancelLabel="Annuleren"
        onConfirm={() => deleting !== null && void remove(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </>
  )
}

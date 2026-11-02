/**
 * Wallets (B-05 SD6, SD15, SD16; AC30, AC33, AC34), admin only:
 *
 * - **Aanmeldcode:** change or clear the sign-up code. Set, it shows the
 *   poster's link `<origin>/speler?code=<code>` (PD20); cleared, sign-up is
 *   closed. Set, it also shows the link's QR code with "Download PNG" and
 *   "Download SVG", disabled at a loopback address, where the printed link
 *   would point at the phone itself (B-09 SD2–SD5). Replacing or clearing a
 *   saved code asks first, since printed QR codes stop working (B-09 SD7).
 *   "QR-code op het scherm" shows the code on the koers screen (B-10 SD5);
 *   it saves at once, with no confirm: nothing printed breaks. It is a
 *   `Switch` (B-12 SD7).
 * - **Bewaartermijnen:** the two retention periods, whole days and months.
 * - **Totalen:** "Tegoed", what the association still owes in drinks, and
 *   "Rood", what players owe, never netted (B-06 SD20, PD10); per borrel the
 *   top-ups net of reversals and the wallet payments net of refunds, newest
 *   first, with "Zonder borrel" for those booked when none was live (PD2).
 * - **The list:** each wallet's name, balance and last activity, with
 *   "Verwijderen" behind a confirm naming the balance that is lost, or the
 *   debt that is written off (B-06 SD8, PD18).
 */
import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { encode } from 'uqr'
import { pngBlob, saveFile, svgDocument } from '../../components/qr/qrFiles'
import { QrSvg } from '../../components/qr/QrSvg'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { Switch } from '../../components/ui/Switch'
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
import { breaksPrinted } from './signupCode'
import { isLoopbackHost, pageAddress, SIGNUP_QR, signupFileName, signupLink } from './signupQr'
import styles from './WalletsSection.module.css'

const NETWORK = 'Verbindingsfout. Probeer opnieuw.'
const PERIODS = 'Kies 1–365 dagen en 1–60 maanden.'
const DOWNLOAD = 'Downloaden lukt niet. Probeer opnieuw.'
const LOOPBACK =
  'Open deze pagina via het netwerkadres (bijv. http://192.168.8.10/) om de QR-code te downloaden.'

function deleteQuestion(wallet: ListedWallet): string {
  const question = `Wallet '${wallet.name}' verwijderen?`
  return wallet.balance_cents < 0
    ? `${question} De schuld van ${formatEuro(-wallet.balance_cents)} vervalt.`
    : `${question} Het saldo van ${formatEuro(wallet.balance_cents)} vervalt.`
}

function codeQuestion(kind: 'change' | 'clear', saved: string): string {
  const question = kind === 'clear' ? 'Aanmelden sluiten?' : 'Aanmeldcode wijzigen?'
  return `${question} Geprinte QR-codes met '${saved}' werken dan niet meer.`
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
  const [pending, setPending] = useState<{
    signupCode: string | null
    kind: 'change' | 'clear'
  } | null>(null)
  const [busy, setBusy] = useState(false)

  // The QR code is the saved code's, never the field's (SD6): one matrix for
  // the preview and both files, so they hold the same modules (AC5).
  const { origin, host, hostname } = pageAddress()
  const saved = settings?.signup_code ?? null
  const modules = useMemo(
    () => (saved === null ? null : encode(signupLink(origin, saved), SIGNUP_QR).data),
    [origin, saved],
  )

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
    const kind = breaksPrinted(settings.signup_code, signupCode)
    if (kind === null) storeCode(signupCode)
    else setPending({ signupCode, kind })
  }

  function storeCode(signupCode: string | null) {
    if (settings === null) return
    void save({ ...settings, signup_code: signupCode }, (text) =>
      setCodeError(text === PERIODS ? 'Kies een code van hoogstens 40 tekens.' : text),
    )
  }

  // The stored settings with the switch flipped; never the code field's unsaved text.
  function storeOnScreen(show: boolean) {
    if (settings === null) return
    void save({ ...settings, show_signup_on_screen: show }, setCodeError)
  }

  async function download(ext: 'png' | 'svg') {
    if (modules === null || saved === null) return
    try {
      const blob =
        ext === 'png'
          ? await pngBlob(modules)
          : new Blob([svgDocument(modules)], { type: 'image/svg+xml' })
      saveFile(blob, signupFileName(host, saved, ext))
      setCodeError(null)
    } catch {
      setCodeError(DOWNLOAD)
    }
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
        <Switch
          label="QR-code op het scherm"
          checked={settings.show_signup_on_screen}
          disabled={busy}
          onChange={storeOnScreen}
        />
        {saved === null || modules === null ? (
          <p className={styles.muted}>Aanmelden is gesloten.</p>
        ) : (
          <>
            <p className={styles.link}>{signupLink(origin, saved)}</p>
            <QrSvg modules={modules} label="Aanmeld-QR-code" className={styles.qr} />
            <div className={styles.row}>
              <Button disabled={isLoopbackHost(hostname)} onClick={() => void download('png')}>
                Download PNG
              </Button>
              <Button disabled={isLoopbackHost(hostname)} onClick={() => void download('svg')}>
                Download SVG
              </Button>
            </div>
            {isLoopbackHost(hostname) && <p className={styles.muted}>{LOOPBACK}</p>}
          </>
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
      <ConfirmDialog
        open={pending !== null}
        message={pending === null ? '' : codeQuestion(pending.kind, settings.signup_code ?? '')}
        confirmLabel={pending?.kind === 'clear' ? 'Wissen' : 'Wijzigen'}
        cancelLabel="Annuleren"
        onConfirm={() => {
          if (pending === null) return
          setPending(null)
          storeCode(pending.signupCode)
        }}
        onCancel={() => setPending(null)}
      />
    </>
  )
}

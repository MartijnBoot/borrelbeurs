/**
 * The kassa page (`/kassa`, B-05 SD22): find a wallet by its typed short code,
 * or by its QR code where the browser allows a camera (SD17), then top it up
 * and see its top-ups. The code goes to the server exactly as
 * typed; the server reads its spelling (AC14). An unknown code is "Onbekende
 * wallet".
 *
 * After every write the wallet is looked up again, so the balance, the
 * 2-minute warning and the list are the server's, never a local sum. "Nieuwe
 * code" (SD14) makes the old code useless, so the page looks the wallet up
 * by the new one from then on, and shows it.
 */
import { type FormEvent, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import { formatEuro } from '../../lib/format'
import { type KassaWallet, lookup, newCode, type Topup, topups, type WalletQuery } from './api'
import { canUseCamera } from './camera'
import { refusalText } from './errors'
import styles from './KassaPage.module.css'
import { MoveDialog } from './MoveDialog'
import { Scanner } from './Scanner'
import { TopupList } from './TopupList'
import { TopUpPanel } from './TopUpPanel'

interface Found {
  query: WalletQuery
  wallet: KassaWallet
  topups: Topup[]
}

export function KassaPage() {
  const [typed, setTyped] = useState('')
  const [found, setFound] = useState<Found | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [moving, setMoving] = useState(false)
  const [renewing, setRenewing] = useState(false)
  const [renewed, setRenewed] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [camera] = useState(canUseCamera)

  async function open(query: WalletQuery) {
    setBusy(true)
    setError(null)
    try {
      const wallet = await lookup(query)
      setFound({ query, wallet, topups: await topups(wallet.wallet_id) })
    } catch (failure) {
      setFound(null)
      setError(refusalText(failure))
    } finally {
      setBusy(false)
    }
  }

  function search(event: FormEvent) {
    event.preventDefault()
    setMoving(false)
    setRenewed(null)
    if (typed.trim()) void open({ short_code: typed })
  }

  async function renew(wallet: KassaWallet) {
    setRenewing(false)
    setError(null)
    try {
      const fresh = await newCode(wallet.wallet_id)
      setRenewed(fresh.short_code)
      await open({ short_code: fresh.short_code })
    } catch (failure) {
      setError(refusalText(failure))
    }
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Kassa</h1>
      <form className={styles.find} onSubmit={search}>
        <Field id="kassa-code" label="Code typen">
          <input
            id="kassa-code"
            type="text"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="characters"
            spellCheck={false}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </Field>
        <div className={styles.actions}>
          <button type="submit" className={styles.primary} disabled={busy}>
            Zoeken
          </button>
          {camera && (
            <Button disabled={busy} onClick={() => setScanning(true)}>
              Camera
            </Button>
          )}
        </div>
      </form>
      {scanning && (
        <Scanner
          onToken={(token) => {
            setScanning(false)
            setMoving(false)
            setRenewed(null)
            void open({ qr_token: token })
          }}
          onClose={() => setScanning(false)}
        />
      )}
      {error !== null && (
        <div className={styles.err} role="alert">
          {error}
        </div>
      )}
      {found !== null && (
        <section className={styles.card} aria-label={found.wallet.name}>
          <h2>{found.wallet.name}</h2>
          <p className={styles.balance}>{formatEuro(found.wallet.balance_cents)}</p>
          <TopUpPanel
            key={found.wallet.wallet_id}
            wallet={found.wallet}
            onBooked={() => void open(found.query)}
          />
          <TopupList topups={found.topups} onReversed={() => void open(found.query)} />
          <div className={styles.actions}>
            <Button onClick={() => setMoving(true)}>Saldo overzetten van…</Button>
            <Button onClick={() => setRenewing(true)}>Nieuwe code</Button>
          </div>
          {renewed !== null && (
            <p className={styles.renewed}>
              Nieuwe code: <strong>{renewed}</strong>
            </p>
          )}
          {moving && (
            <MoveDialog
              target={found.wallet}
              onMoved={() => {
                setMoving(false)
                void open(found.query)
              }}
              onClose={() => setMoving(false)}
            />
          )}
          <ConfirmDialog
            open={renewing}
            message={
              `Nieuwe code maken voor ${found.wallet.name}?` +
              ' De oude QR-code en code werken dan niet meer.'
            }
            confirmLabel="Nieuwe code"
            cancelLabel="Annuleren"
            onConfirm={() => void renew(found.wallet)}
            onCancel={() => setRenewing(false)}
          />
        </section>
      )}
    </div>
  )
}

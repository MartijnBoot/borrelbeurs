/**
 * The bar's wallet picker (B-06 SD4, SD12, SD13): "Code typen" with "Zoeken",
 * and "Camera" only where the browser allows one (AC32) -- at the venue, over
 * plain HTTP on a LAN address, it offers the code field alone, with no error.
 * The code goes to the server exactly as typed; the server reads its spelling.
 *
 * A found wallet is handed to `onFound` with the query that found it, which the
 * order then carries (SD13). A 404 is "Onbekende wallet"; any other failure
 * "Verbindingsfout. Probeer opnieuw." (PD18). On either, no wallet is held and
 * the typed code stays. Only the latest lookup counts, as at the kassa.
 */
import { type FormEvent, useRef, useState } from 'react'
import { canUseCamera } from '../../components/scanner/camera'
import { Scanner } from '../../components/scanner/Scanner'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { HttpError } from '../../lib/http'
import type { WalletQuery } from './api/orders'
import { lookupWallet } from './api/wallets'
import type { HeldWallet } from './model/barController'
import styles from './Wallet.module.css'

const UNKNOWN = 'Onbekende wallet'
const NETWORK = 'Verbindingsfout. Probeer opnieuw.'

export function WalletPicker({
  disabled,
  onFound,
}: {
  disabled: boolean
  onFound: (wallet: HeldWallet) => void
}) {
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [camera] = useState(canUseCamera)
  const latest = useRef(0)

  async function find(query: WalletQuery) {
    const asked = ++latest.current
    setBusy(true)
    setError(null)
    try {
      const found = await lookupWallet(query)
      if (asked === latest.current) onFound({ query, ...found })
    } catch (failure) {
      if (asked === latest.current) {
        setError(failure instanceof HttpError && failure.status === 404 ? UNKNOWN : NETWORK)
      }
    } finally {
      if (asked === latest.current) setBusy(false)
    }
  }

  function search(event: FormEvent) {
    event.preventDefault()
    if (typed.trim()) void find({ short_code: typed })
  }

  return (
    <div className={styles.picker}>
      <form className={styles.find} onSubmit={search}>
        <Field id="bar-wallet-code" label="Code typen">
          <input
            id="bar-wallet-code"
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
          <Button type="submit" disabled={disabled || busy}>
            Zoeken
          </Button>
          {camera && (
            <Button disabled={disabled || busy} onClick={() => setScanning(true)}>
              Camera
            </Button>
          )}
        </div>
      </form>
      {scanning && (
        <Scanner
          onToken={(token) => {
            setScanning(false)
            void find({ qr_token: token })
          }}
          onClose={() => setScanning(false)}
        />
      )}
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

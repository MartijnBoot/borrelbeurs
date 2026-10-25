/**
 * The kassa page (`/kassa`, B-05 SD22): find a wallet by its typed short code,
 * then top it up and see its top-ups. The code goes to the server exactly as
 * typed; the server reads its spelling (AC14). An unknown code is "Onbekende
 * wallet".
 *
 * After every write the wallet is looked up again, so the balance, the
 * 2-minute warning and the list are the server's, never a local sum.
 */
import { type FormEvent, useState } from 'react'
import { Field } from '../../components/ui/Field'
import { formatEuro } from '../../lib/format'
import { HttpError } from '../../lib/http'
import { type KassaWallet, lookup, type Topup, topups, type WalletQuery } from './api'
import styles from './KassaPage.module.css'
import { TopupList } from './TopupList'
import { TopUpPanel } from './TopUpPanel'

interface Found {
  query: WalletQuery
  wallet: KassaWallet
  topups: Topup[]
}

function failureText(error: unknown): string {
  if (error instanceof HttpError && error.code === 'wallet_not_found') return 'Onbekende wallet'
  return 'Verbindingsfout. Probeer opnieuw.'
}

export function KassaPage() {
  const [typed, setTyped] = useState('')
  const [found, setFound] = useState<Found | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function open(query: WalletQuery) {
    setBusy(true)
    setError(null)
    try {
      const wallet = await lookup(query)
      setFound({ query, wallet, topups: await topups(wallet.wallet_id) })
    } catch (failure) {
      setFound(null)
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  function search(event: FormEvent) {
    event.preventDefault()
    if (typed.trim()) void open({ short_code: typed })
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
        <button type="submit" className={styles.primary} disabled={busy}>
          Zoeken
        </button>
      </form>
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
          <TopupList topups={found.topups} />
        </section>
      )}
    </div>
  )
}

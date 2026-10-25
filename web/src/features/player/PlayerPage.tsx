/**
 * `/speler` (B-05 SD20, SD21): outside the crew shell, needing no session. The
 * wallet cookie decides what shows: sign-up without one (a 401 `no_wallet`,
 * AC13), the wallet with one. A network failure offers a retry.
 */
import { useCallback, useEffect, useState } from 'react'
import { Logo } from '../../components/ui/Logo'
import { getWallet, isNoWallet, type Wallet } from './api'
import styles from './PlayerPage.module.css'
import { SignupForm } from './SignupForm'

type State =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'failed' }
  | { status: 'ready'; wallet: Wallet }

export function PlayerPage() {
  const [state, setState] = useState<State>({ status: 'loading' })

  const load = useCallback(
    () =>
      getWallet().then(
        (wallet) => setState({ status: 'ready', wallet }),
        (failure: unknown) => setState({ status: isNoWallet(failure) ? 'none' : 'failed' }),
      ),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  return (
    <main className={styles.wrap}>
      <Logo alt="Beurs Borrel" className={styles.logo} />
      {state.status === 'none' && (
        <SignupForm onSignedUp={(wallet) => setState({ status: 'ready', wallet })} />
      )}
      {state.status === 'failed' && (
        <div className={styles.card}>
          <p role="alert">Verbindingsfout. Probeer opnieuw.</p>
          <button type="button" className={styles.primary} onClick={() => void load()}>
            Opnieuw
          </button>
        </div>
      )}
      {state.status === 'ready' && (
        <div className={styles.card}>
          <h1>{state.wallet.name}</h1>
        </div>
      )}
    </main>
  )
}

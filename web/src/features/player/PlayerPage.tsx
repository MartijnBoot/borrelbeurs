/**
 * `/speler` (B-05 SD20, SD21): outside the crew shell, needing no session. The
 * wallet cookie decides what shows: sign-up without one (a 401 `no_wallet`,
 * AC13), the wallet with one. A network failure offers a retry.
 *
 * The wallet refreshes while the page is visible (AC10). A refresh's 401 means
 * the wallet was deleted or moved meanwhile: sign-up (AC13). A failed refresh
 * keeps what is shown and the next one tries again.
 */
import { useCallback, useEffect, useState } from 'react'
import { Logo } from '../../components/ui/Logo'
import { getWallet, isNoWallet, type Wallet } from './api'
import styles from './PlayerPage.module.css'
import { SignupForm } from './SignupForm'
import { useVisiblePoll } from './useVisiblePoll'
import { WalletView } from './WalletView'

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
        <LiveWallet
          wallet={state.wallet}
          onWallet={(wallet) => setState({ status: 'ready', wallet })}
          onGone={() => setState({ status: 'none' })}
        />
      )}
    </main>
  )
}

function LiveWallet({
  wallet,
  onWallet,
  onGone,
}: {
  wallet: Wallet
  onWallet: (wallet: Wallet) => void
  onGone: () => void
}) {
  useVisiblePoll(() => {
    getWallet().then(onWallet, (failure: unknown) => {
      if (isNoWallet(failure)) onGone()
    })
  })
  return <WalletView wallet={wallet} onDeleted={onGone} />
}

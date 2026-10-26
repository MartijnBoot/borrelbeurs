/**
 * The player's wallet (B-05 SD21, AC9, AC29): the name, the balance, the QR code,
 * the short code as served, "Wallet verwijderen" behind a confirm, and the hint
 * to keep the page. Nothing else: no prices, no history, no top-up.
 *
 * A debt shows with its minus sign, and deleting a wallet in debt says to top up
 * first and sends nothing (B-06 SD8, SD19; PD19): B-05's confirm, "Je saldo van
 * … vervalt.", would be false for a debt.
 */
import { useState } from 'react'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatBalance, formatEuro } from '../../lib/format'
import { deleteWallet, isBalanceNegative, isNoWallet, type Wallet } from './api'
import styles from './PlayerPage.module.css'
import { QrCode } from './QrCode'

const TOP_UP_FIRST = 'Eerst aanvullen bij de kassa'

export function WalletView({ wallet, onDeleted }: { wallet: Wallet; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function ask() {
    if (wallet.balance_cents < 0) setError(TOP_UP_FIRST)
    else setConfirming(true)
  }

  async function remove() {
    setConfirming(false)
    try {
      await deleteWallet()
      onDeleted()
    } catch (failure) {
      if (isNoWallet(failure)) onDeleted()
      else if (isBalanceNegative(failure)) setError(TOP_UP_FIRST)
      else setError('Verbindingsfout. Probeer opnieuw.')
    }
  }

  return (
    <div className={styles.card}>
      <h1>{wallet.name}</h1>
      <p className={styles.balance}>{formatBalance(wallet.balance_cents)}</p>
      <QrCode token={wallet.qr_token} />
      <p className={styles.code}>{wallet.short_code}</p>
      <p className={styles.hint}>Bewaar deze pagina — je wallet staat op deze telefoon.</p>
      <button type="button" className={styles.danger} onClick={ask}>
        Wallet verwijderen
      </button>
      {error !== null && (
        <div className={styles.err} role="alert">
          {error}
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        message={`Je saldo van ${formatEuro(wallet.balance_cents)} vervalt.`}
        confirmLabel="Wallet verwijderen"
        cancelLabel="Annuleren"
        onConfirm={() => void remove()}
        onCancel={() => setConfirming(false)}
      />
    </div>
  )
}

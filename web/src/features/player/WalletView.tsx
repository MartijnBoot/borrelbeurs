/**
 * The player's wallet (B-05 SD21, AC9, AC29): the name, the balance, the QR code,
 * the short code as served, "Wallet verwijderen" behind a confirm, and the hint
 * to keep the page. Nothing else: no prices, no history, no top-up.
 */
import { useState } from 'react'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { deleteWallet, isNoWallet, type Wallet } from './api'
import styles from './PlayerPage.module.css'
import { QrCode } from './QrCode'

export function WalletView({ wallet, onDeleted }: { wallet: Wallet; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function remove() {
    setConfirming(false)
    try {
      await deleteWallet()
      onDeleted()
    } catch (failure) {
      if (isNoWallet(failure)) onDeleted()
      else setError('Verbindingsfout. Probeer opnieuw.')
    }
  }

  return (
    <div className={styles.card}>
      <h1>{wallet.name}</h1>
      <p className={styles.balance}>{formatEuro(wallet.balance_cents)}</p>
      <QrCode token={wallet.qr_token} />
      <p className={styles.code}>{wallet.short_code}</p>
      <p className={styles.hint}>Bewaar deze pagina — je wallet staat op deze telefoon.</p>
      <button type="button" className={styles.danger} onClick={() => setConfirming(true)}>
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

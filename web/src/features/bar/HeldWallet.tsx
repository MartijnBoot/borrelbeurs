/**
 * The wallet the bar holds (B-06 SD4, SD6, SD13): its name large, for as long as
 * it is held, and its balance, with a minus when in debt (SD19). Nothing else
 * of the wallet is shown. "Andere wallet" lets go of it, "Annuleren" of it and
 * the basket; neither works while the basket's order is open (PD12).
 */
import { Button } from '../../components/ui/Button'
import { formatBalance } from '../../lib/format'
import type { HeldWallet as Held } from './model/barController'
import styles from './Wallet.module.css'

export function HeldWallet({
  wallet,
  locked,
  onOther,
  onCancel,
}: {
  wallet: Held
  locked: boolean
  onOther: () => void
  onCancel: () => void
}) {
  return (
    <section className={styles.held} aria-label="Wallet">
      <strong className={styles.name}>{wallet.name}</strong>
      <span className={styles.balance}>saldo {formatBalance(wallet.balance_cents)}</span>
      <span className={styles.actions}>
        <Button disabled={locked} onClick={onOther}>
          Andere wallet
        </Button>
        <Button disabled={locked} onClick={onCancel}>
          Annuleren
        </Button>
      </span>
    </section>
  )
}

/**
 * The wallet the bar holds (B-06 SD4, SD6, SD13): its name large, for as long as
 * it is held, and its balance, with a minus when in debt (SD19). Nothing else
 * of the wallet is shown.
 */
import { formatBalance } from '../../lib/format'
import type { HeldWallet as Held } from './model/barController'
import styles from './Wallet.module.css'

export function HeldWallet({ wallet }: { wallet: Held }) {
  return (
    <section className={styles.held} aria-label="Wallet">
      <strong className={styles.name}>{wallet.name}</strong>
      <span className={styles.balance}>saldo {formatBalance(wallet.balance_cents)}</span>
    </section>
  )
}

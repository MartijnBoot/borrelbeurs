/**
 * The financial overview (Phase 5 SD15): the server's aggregates and nothing
 * derived. Totals are sums of the server's per-drink `qty` and
 * `revenue_cents` (`selectTotals`); there is no price × quantity anywhere
 * (AC17). Pending taps never move it -- only an `order` message or a
 * snapshot does (AC16, AC18). Bar-price figures, the sales count and the
 * download are Phase 7's (D-20), so they are absent.
 *
 * A drink removed from the run (Phase 6 SD13) is listed only if it sold, as
 * "{name} (verwijderd)"; the totals still sum every drink.
 */
import { useShallow } from 'zustand/react/shallow'
import { formatEuro } from '../../lib/format'
import { selectDrinks, selectEarnings, selectTotals, useExchange } from '../exchange'
import styles from './FinancialPanel.module.css'

export function FinancialPanel() {
  const drinks = useExchange(selectDrinks)
  const earnings = useExchange(selectEarnings)
  const totals = useExchange(useShallow(selectTotals))
  return (
    <section className={styles.panel}>
      <h2 className={styles.title}>💶 Financieel overzicht</h2>
      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <span className={styles.label}>Totale omzet</span>
          <span className={styles.value} data-testid="total-revenue">
            {formatEuro(totals.revenueCents)}
          </span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.label}>Totaal aantal drankjes</span>
          <span className={styles.value} data-testid="total-qty">
            {totals.qty}
          </span>
        </div>
      </div>
      <ul className={styles.drinks}>
        {drinks.map(({ drink_id, name, active }) => {
          const line = earnings[drink_id] ?? { qty: 0, revenue_cents: 0 }
          if (!active && line.qty === 0) return null
          return (
            <li key={drink_id}>
              {active ? name : `${name} (verwijderd)`}: {line.qty}× —{' '}
              {formatEuro(line.revenue_cents)}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/**
 * The bar page (`/bar`, Phase 5 SD18): v1's layout -- "🍺 Bar — Bestellen",
 * then a "Bestellingen" card (pad, pending list, 409 dialog) beside a
 * "💶 Financieel overzicht" card (panel and revenue chart), stacked at
 * ≤1000 px.
 *
 * With no live run it shows only "Geen actieve borrel" (SD14): no pad, no
 * panel and no controller. The same page shows the cards once a snapshot
 * arrives, without a reload (AC27).
 */
import { selectEmpty, useExchange } from '../exchange'
import { FinancialPanel } from './FinancialPanel'
import { OrderConflict } from './OrderConflict'
import { OrderPad } from './OrderPad'
import { PendingOrders } from './PendingOrders'
import { RevenueChart } from './RevenueChart'
import { useBarController } from './useBarController'
import styles from './BarPage.module.css'

export function BarPage() {
  const empty = useExchange(selectEmpty)
  return (
    <div className={styles.page}>
      <h1 className={styles.title}>🍺 Bar — Bestellen</h1>
      {empty ? <p className={styles.empty}>Geen actieve borrel</p> : <LiveBar />}
    </div>
  )
}

function LiveBar() {
  const { view, actions } = useBarController()
  return (
    <div className={styles.cards}>
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Bestellingen</h2>
        <OrderPad view={view} actions={actions} />
        <PendingOrders view={view} actions={actions} />
        <OrderConflict view={view} actions={actions} />
      </section>
      <section className={styles.card}>
        <FinancialPanel />
        <div className={styles.chart}>
          <RevenueChart />
        </div>
      </section>
    </div>
  )
}

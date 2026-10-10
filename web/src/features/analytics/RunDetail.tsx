/**
 * A run's detail (Phase 7 SD10; AC27, AC30): one row per product that sold --
 * removed drinks included, marked "verwijderd" -- with quantity, revenue,
 * revenue at the bar price and average price, then the run's totals, and the
 * earnings series below. Every amount is the server's, in cents, shown in
 * euros. A run without sales shows "Geen verkopen".
 */
import { useEffect, useState } from 'react'
import { formatEuro } from '../../lib/format'
import styles from './analytics.module.css'
import { fetchRunDetail, type RunDetailData } from './api/runDetail'
import { SeriesChart } from './SeriesChart'

export interface RunDetailProps {
  runId: number
}

export function RunDetail({ runId }: RunDetailProps) {
  const [detail, setDetail] = useState<RunDetailData | undefined>(undefined)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let current = true
    fetchRunDetail(runId).then(
      (data) => {
        if (!current) return
        setDetail(data)
        setFailed(false)
      },
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [runId])

  if (failed) return <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>
  // A detail fetched for the previous run is not shown while this one loads.
  if (detail?.run_id !== runId) return <p className={styles.muted}>Laden…</p>
  return (
    <>
      {detail.per_product.length === 0 ? (
        <p className={styles.muted}>Geen verkopen</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Drankje</th>
                <th className={styles.number}>Aantal</th>
                <th className={styles.number}>Omzet</th>
                <th className={styles.number}>Omzet tegen barprijs</th>
                <th className={styles.number}>Gemiddelde prijs</th>
              </tr>
            </thead>
            <tbody>
              {detail.per_product.map((row) => (
                <tr key={row.product_key}>
                  <td>
                    {row.name}
                    {row.removed && <span className={styles.muted}> verwijderd</span>}
                  </td>
                  <td className={styles.number}>{row.qty}</td>
                  <td className={styles.number}>{formatEuro(row.revenue_cents)}</td>
                  <td className={styles.number}>{formatEuro(row.bar_price_total_cents)}</td>
                  <td className={styles.number}>{formatEuro(row.avg_price_cents)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Totaal</th>
                <td className={styles.number}>{detail.qty}</td>
                <td className={styles.number}>{formatEuro(detail.revenue_cents)}</td>
                <td className={styles.number}>{formatEuro(detail.bar_price_total_cents)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <SeriesChart runId={detail.run_id} />
    </>
  )
}

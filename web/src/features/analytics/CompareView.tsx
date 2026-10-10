/**
 * Two runs side by side (Phase 7 SD10; AC11, AC28, AC30): per product --
 * joined on the product by the server, so a renamed drink is one row --
 * quantity and revenue in A and in B, "—" where a product did not sell. Below,
 * a product select drives `PriceCurveChart`. Until both runs are chosen, "Kies
 * twee borrels" and no request.
 */
import { useEffect, useState } from 'react'
import { Select } from '../../components/ui/Select'
import { formatEuro } from '../../lib/format'
import styles from './analytics.module.css'
import { type CompareRow, fetchCompare } from './api/compare'
import { PriceCurveChart } from './PriceCurveChart'

export interface CompareViewProps {
  a: number | null
  b: number | null
}

export function CompareView({ a, b }: CompareViewProps) {
  if (a === null || b === null) return <p className={styles.muted}>Kies twee borrels</p>
  return <Comparison a={a} b={b} />
}

function Comparison({ a, b }: { a: number; b: number }) {
  const [loaded, setLoaded] = useState<{ key: string; rows: CompareRow[] } | null>(null)
  const [failed, setFailed] = useState(false)
  const [chosen, setChosen] = useState<string | null>(null)
  const key = `${a}:${b}`

  useEffect(() => {
    let current = true
    fetchCompare(a, b).then(
      (rows) => {
        if (!current) return
        setLoaded({ key: `${a}:${b}`, rows })
        setFailed(false)
      },
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [a, b])

  if (failed) return <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>
  if (loaded?.key !== key) return <p className={styles.muted}>Laden…</p>
  const { rows } = loaded
  if (rows.length === 0) return <p className={styles.muted}>Geen verkopen</p>

  const products = rows.flatMap((row) =>
    row.product_id === null ? [] : [{ value: String(row.product_id), label: row.name }],
  )
  const product = products.find((p) => p.value === chosen) ?? products[0]
  const dash = (value: number | undefined, format: (n: number) => string = String) =>
    value === undefined ? '—' : format(value)

  return (
    <>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Drankje</th>
              <th className={styles.number}>Aantal A</th>
              <th className={styles.number}>Omzet A</th>
              <th className={styles.number}>Aantal B</th>
              <th className={styles.number}>Omzet B</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.product_key}>
                <td>{row.name}</td>
                <td className={styles.number}>{dash(row.a?.qty)}</td>
                <td className={styles.number}>{dash(row.a?.revenue_cents, formatEuro)}</td>
                <td className={styles.number}>{dash(row.b?.qty)}</td>
                <td className={styles.number}>{dash(row.b?.revenue_cents, formatEuro)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {product !== undefined && (
        <>
          <Select label="Drankje" value={product.value} options={products} onChange={setChosen} />
          <PriceCurveChart productId={Number(product.value)} a={a} b={b} />
        </>
      )}
    </>
  )
}

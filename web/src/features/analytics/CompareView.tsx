/**
 * Two runs side by side (Phase 7 SD10): per product, and a price-curve overlay.
 * Until both are chosen, "Kies twee borrels". The comparison itself is a stub
 * until T22 fills it; its props are final.
 */
import styles from './analytics.module.css'

export interface CompareViewProps {
  a: number | null
  b: number | null
}

export function CompareView({ a, b }: CompareViewProps) {
  if (a === null || b === null) return <p className={styles.muted}>Kies twee borrels</p>
  return null
}

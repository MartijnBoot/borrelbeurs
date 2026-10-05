import styles from './StatusDot.module.css'

export type DotStatus = 'ok' | 'warn' | 'down'

/** A coloured dot; `label` is its accessible name, since colour alone says nothing. */
export function StatusDot({ status, label }: { status: DotStatus; label: string }) {
  return <span role="img" aria-label={label} className={`${styles.dot} ${styles[status]}`} />
}

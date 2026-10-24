/** An on/off control (Phase 6 SD27): a `role="switch"` button, controlled by its owner. */
import { type Explanation, InfoButton } from './InfoButton'
import styles from './Switch.module.css'

export interface SwitchProps {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  /** B-01: an (i) beside the switch -- never inside it, which would change its name. */
  info?: Explanation
}

export function Switch({ label, checked, onChange, disabled = false, info }: SwitchProps) {
  const toggle = (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={styles.switch}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
      <span>{label}</span>
    </button>
  )
  if (info === undefined) return toggle
  return (
    <span className={styles.row}>
      {toggle}
      <InfoButton explanation={info} />
    </span>
  )
}

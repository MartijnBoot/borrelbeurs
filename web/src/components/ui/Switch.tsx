/** An on/off control (Phase 6 SD27): a `role="switch"` button, controlled by its owner. */
import styles from './Switch.module.css'

export interface SwitchProps {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}

export function Switch({ label, checked, onChange, disabled = false }: SwitchProps) {
  return (
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
}

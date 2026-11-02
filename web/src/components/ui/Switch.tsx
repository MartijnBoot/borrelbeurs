/**
 * An on/off control (Phase 6 SD27): a `role="switch"` button, controlled by its owner.
 *
 * B-12 SD7, PD14: one fixed-width row -- the label, then its (i), then the
 * track at the row's right end -- so the switches of a section line up in one
 * column. The button holds only the track and is named by the `<label>`, so
 * the (i) stays outside its name (B-01), and a click on the label toggles too.
 */
import { useId } from 'react'
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
  const id = useId()
  return (
    <span className={styles.row}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {info !== undefined && <InfoButton explanation={info} />}
      <button
        id={id}
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
      </button>
    </span>
  )
}

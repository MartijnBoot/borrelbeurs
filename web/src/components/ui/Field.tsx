import type { ReactNode } from 'react'
import styles from './Field.module.css'

export interface FieldProps {
  /** The input's id; the label and the hint/error texts point at it. */
  id: string
  label: string
  hint?: string
  error?: string
  children: ReactNode
}

/** A labelled form control with an optional hint and error (SD27). */
export function Field({ id, label, hint, error, children }: FieldProps) {
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {children}
      {hint !== undefined && (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      )}
      {error !== undefined && (
        <span id={`${id}-error`} className={styles.error} role="alert">
          {error}
        </span>
      )}
    </div>
  )
}

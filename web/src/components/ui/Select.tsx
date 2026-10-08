/** A labelled native select (Phase 6 SD27): string values in and out. */
import { useId } from 'react'
import { Field } from './Field'
import styles from './Field.module.css'

export interface SelectOption<T extends string> {
  value: T
  label: string
}

export interface SelectProps<T extends string> {
  label: string
  value: T
  options: readonly SelectOption<T>[]
  onChange: (value: T) => void
  hint?: string
}

export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  hint,
}: SelectProps<T>) {
  const id = useId()
  return (
    <Field id={id} label={label} hint={hint}>
      <select
        id={id}
        className={styles.input}
        value={value}
        onChange={(event) => {
          const chosen = options.find((option) => option.value === event.target.value)
          if (chosen !== undefined) onChange(chosen.value)
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  )
}

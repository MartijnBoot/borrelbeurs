/**
 * A number input that never invents a value (Phase 6 SD27; AC1, AC3; D-03).
 *
 * Controlled by `value: number | null`; the text typed stays inside, so "0," is
 * kept while it is being typed. Each edit reports to `onChange`: `null` for an
 * empty field -- never 0 --, the number for a valid entry, `'invalid'` for
 * anything else. An untouched field reports nothing, so its owner can leave it
 * out of a request. A decimal comma or point both parse; no `+x` coercion.
 */
import { useId, useState } from 'react'
import { type FieldValue, numberText, parseNumber } from '../../lib/format'
import { Field } from './Field'
import styles from './Field.module.css'
import { describedBy } from './fieldAria'

export interface NumberFieldProps {
  label: string
  value: number | null
  onChange: (value: FieldValue) => void
  hint?: string
  error?: string
  /** Text only: a number here would read as a value the field does not hold. */
  placeholder?: string
}

export function NumberField(props: NumberFieldProps) {
  return <TextNumberField {...props} parse={parseNumber} format={numberText} />
}

interface TextNumberFieldProps<T> {
  label: string
  value: T | null
  onChange: (value: T | null | 'invalid') => void
  parse: (text: string) => T | null | 'invalid'
  format: (value: T | null) => string
  hint?: string
  error?: string
  placeholder?: string
  inputMode?: 'decimal'
}

/** The shared body of `NumberField` and `MoneyField`: owner's value in, parsed edits out. */
export function TextNumberField<T>({
  label,
  value,
  onChange,
  parse,
  format,
  hint,
  error,
  placeholder,
}: TextNumberFieldProps<T>) {
  const id = useId()
  const [text, setText] = useState(() => format(value))
  const [shown, setShown] = useState(value)
  // A new value from the owner (a reload, "Overnemen") replaces the text --
  // unless the text already says it, so typing "0," over 0 is not undone.
  if (!Object.is(value, shown)) {
    setShown(value)
    if (!Object.is(parse(text), value)) setText(format(value))
  }
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        className={styles.input}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        value={text}
        placeholder={placeholder}
        aria-invalid={error !== undefined || undefined}
        aria-describedby={describedBy(id, hint, error)}
        onChange={(event) => {
          setText(event.target.value)
          onChange(parse(event.target.value))
        }}
      />
    </Field>
  )
}

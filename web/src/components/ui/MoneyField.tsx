/**
 * A euro amount as integer cents (Phase 6 SD5, SD27): "2,50" or "2.50" is 250,
 * exactly (`parseEuroCents`); empty is `null`; three decimals is `'invalid'`,
 * never rounded. Otherwise a `NumberField`.
 */
import { centsText, type FieldValue, parseEuroCents } from '../../lib/format'
import { TextNumberField } from './NumberField'

export interface MoneyFieldProps {
  label: string
  cents: FieldValue
  onChange: (cents: FieldValue) => void
  hint?: string
  error?: string
  placeholder?: string
}

export function MoneyField({ cents, ...rest }: MoneyFieldProps) {
  return (
    <TextNumberField
      {...rest}
      value={cents}
      parse={parseEuroCents}
      format={(value) => (value === null ? '' : centsText(value))}
    />
  )
}

// A duration field's whole seconds (Phase 6 SD22, SD23), shared by market events and the jump.
import type { FieldValue } from '../../lib/format'

/** Whole seconds in `[min, max]`, or `null`. */
export function seconds(value: FieldValue, min: number, max: number): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max
    ? value
    : null
}

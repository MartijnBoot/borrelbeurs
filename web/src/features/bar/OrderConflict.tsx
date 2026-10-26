/**
 * The head 409 in a `ConfirmDialog` (Phase 5 SD9; B-06 SD4, AC11). The prices
 * shown are the 409 response's own, from the conflict's record -- never the
 * store's: every basket line whose price changed, "<drank>: <€ oud> → <€ nieuw>",
 * and the new total. "Bevestigen" posts the same lines and wallet at exactly
 * that record with a new key (AC12, AC13); "Annuleren" sends nothing and keeps
 * the basket. Conflicts queue in the intents and surface here one at a time
 * (AC14); the next one's "Bevestigen" ignores taps for `CONFIRM_GUARD_MS` after
 * an answer, so a double tap cannot confirm it unread.
 */
import { useRef } from 'react'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { selectDrinks, useExchange } from '../exchange'
import { totalCents } from './model/basket'
import type { BarView } from './model/barController'
import { CONFIRM_GUARD_MS } from './model/constants'
import type { BarActions } from './useBarController'
import styles from './OrderConflict.module.css'

export interface OrderConflictProps {
  view: Pick<BarView, 'headConflict'>
  actions: Pick<BarActions, 'confirm' | 'cancel'>
}

export function OrderConflict({ view, actions }: OrderConflictProps) {
  const drinks = useExchange(selectDrinks)
  const answeredAt = useRef<number | null>(null)
  const head = view.headConflict
  if (head === null) return null
  const nameOf = (id: number) => drinks.find((d) => d.drink_id === id)?.name ?? `#${id}`
  const changed = head.body.lines.filter(
    (line) => head.quote.prices[line.drink_id] !== line.unit_price_cents,
  )
  const total = totalCents(head.lines, head.quote)
  return (
    <ConfirmDialog
      // A new conflict is a new dialog: focus starts on confirm again.
      key={`${head.id}:${head.quote.version}`}
      open
      message={
        <>
          <span>Prijzen zijn veranderd:</span>
          <ul className={styles.changes}>
            {changed.map((line) => (
              <li key={line.drink_id}>
                {nameOf(line.drink_id)}: {formatEuro(line.unit_price_cents)} →{' '}
                {formatEuro(head.quote.prices[line.drink_id])}
              </li>
            ))}
          </ul>
          <span>Nieuw totaal: {total === null ? '—' : formatEuro(total)}</span>
        </>
      }
      confirmLabel="Bevestigen"
      cancelLabel="Annuleren"
      onConfirm={() => {
        const last = answeredAt.current
        if (last !== null && performance.now() - last < CONFIRM_GUARD_MS) return
        answeredAt.current = performance.now()
        actions.confirm()
      }}
      onCancel={() => {
        answeredAt.current = performance.now()
        actions.cancel()
      }}
    />
  )
}

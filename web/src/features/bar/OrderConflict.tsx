/**
 * The head 409 in a `ConfirmDialog` (Phase 5 SD9). The price shown is the
 * 409 response's own, from the conflict's record -- never the store's -- and
 * "Bevestigen" posts exactly that record with a new key (AC12, AC13).
 * Conflicts queue in the intents and surface here one at a time (AC14).
 */
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { formatEuro } from '../../lib/format'
import { selectDrinks, useExchange } from '../exchange'
import type { BarView } from './model/barController'
import type { BarActions } from './useBarController'

export interface OrderConflictProps {
  view: Pick<BarView, 'headConflict'>
  actions: Pick<BarActions, 'confirm' | 'cancel'>
}

export function OrderConflict({ view, actions }: OrderConflictProps) {
  const drinks = useExchange(selectDrinks)
  const head = view.headConflict
  if (head === null) return null
  const name = drinks.find((d) => d.drink_id === head.drinkId)?.name ?? `#${head.drinkId}`
  const price = head.quote.prices[head.drinkId]
  return (
    <ConfirmDialog
      // A new conflict is a new dialog: focus starts on confirm again.
      key={`${head.id}:${head.quote.version}`}
      open
      message={`${name}: prijs is nu ${formatEuro(price)} — bevestigen?`}
      confirmLabel="Bevestigen"
      cancelLabel="Annuleren"
      onConfirm={actions.confirm}
      onCancel={actions.cancel}
    />
  )
}

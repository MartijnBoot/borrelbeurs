/**
 * The bar controller (Phase 5 PD8): the **only** path from a tap to a request
 * body. It joins the store, the hold buffer and the order intents:
 *
 * - every new store `quote` is offered to the hold buffer (SD1);
 * - a `snapshotGen` change -- any snapshot, WebSocket or poll -- promotes
 *   (PD3), as do an accepted order or a 409 (`onPromote`) and `refresh()`
 *   ("Ververs") (SD3);
 * - `tap(drinkId)` reads `displayed` **once** and hands that `Quote` to the
 *   intents. It is refused with no displayed quote, a stale latest one (AC8)
 *   or an open conflict (AC14).
 *
 * Components call only this, through `useBarController`; the property test
 * drives the same object. `view` is a new frozen object on every change, so
 * it serves `useSyncExternalStore` directly.
 */
import type { DrinkId, ExchangeState, Quote } from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { createHoldBuffer, isStale } from './holdBuffer'
import { createOrderIntents, type Conflict, type OrderEntry } from './orderIntents'

export interface BarView {
  readonly displayed: Quote | null
  readonly latest: Quote | null
  readonly entries: readonly OrderEntry[]
  readonly headConflict: Conflict | null
}

export interface BarControllerDeps<Id = unknown> {
  store: {
    getState(): ExchangeState
    subscribe(listener: (state: ExchangeState) => void): () => void
  }
  /** The monotonic clock: quote age and staleness (SD4). */
  now(): number
  setTimeout(fn: () => void, ms: number): Id
  clearTimeout(id: Id): void
  post(request: { key: string; body: OrderBody }): Promise<OrderOutcome>
  uuid(): string
}

export interface BarController {
  readonly view: BarView
  subscribe(listener: () => void): () => void
  press(): void
  release(): void
  /** The new entry's id, or `null` when the tap is refused. */
  tap(drinkId: DrinkId): number | null
  refresh(): void
  confirm(): void
  cancel(): void
  retry(id: number): void
  dismiss(id: number): void
  dispose(): void
}

export function createBarController<Id>(deps: BarControllerDeps<Id>): BarController {
  const listeners = new Set<() => void>()
  let view: BarView | null = null

  function changed() {
    view = null
    for (const listener of listeners) listener()
  }

  const hold = createHoldBuffer({
    setTimeout: deps.setTimeout,
    clearTimeout: deps.clearTimeout,
    onChange: changed,
  })
  const intents = createOrderIntents({
    post: deps.post,
    uuid: deps.uuid,
    now: deps.now,
    setTimeout: deps.setTimeout,
    clearTimeout: deps.clearTimeout,
    onChange: changed,
    onPromote: () => hold.promote(),
  })

  let { quote, snapshotGen } = deps.store.getState()
  hold.offer(quote)
  const unsubscribe = deps.store.subscribe((state) => {
    if (state.quote !== quote) {
      quote = state.quote
      hold.offer(quote)
    }
    if (state.snapshotGen !== snapshotGen) {
      snapshotGen = state.snapshotGen
      hold.promote()
    }
  })

  return {
    get view() {
      view ??= Object.freeze({
        displayed: hold.displayed,
        latest: hold.latest,
        entries: intents.entries,
        headConflict: intents.headConflict,
      })
      return view
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    press: () => hold.pressStart(),
    release: () => hold.pressEnd(),
    tap(drinkId) {
      const displayed = hold.displayed
      if (displayed === null || isStale(hold.latest, deps.now())) return null
      if (intents.headConflict !== null) return null
      return intents.create(displayed, drinkId)
    },
    refresh: () => hold.promote(),
    confirm: () => intents.confirm(),
    cancel: () => intents.cancel(),
    retry: (id) => intents.retry(id),
    dismiss: (id) => intents.dismiss(id),
    dispose() {
      unsubscribe()
      hold.dispose()
      intents.dispose()
      listeners.clear()
    },
  }
}

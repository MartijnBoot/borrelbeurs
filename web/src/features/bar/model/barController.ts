/**
 * The bar controller (Phase 5 PD8): the **only** path from a tap to a request
 * body. It joins the store, the hold buffer and the order intents:
 *
 * - every new store `quote` is offered to the hold buffer (SD1);
 * - a `snapshotGen` change -- any snapshot, WebSocket or poll -- promotes
 *   (PD3), as do an accepted order or a 409 (`onPromote`) and `refresh()`
 *   ("Ververs") (SD3);
 * - B-06 (SD4, PD12): a drink tap `add`s to the basket and sends nothing;
 *   `remove` and `clear` edit it. `checkout()` reads `displayed` **once** and
 *   hands that `Quote` and the basket to the intents. It is refused with no
 *   displayed quote, a stale latest one (AC8), an open conflict (AC14), an
 *   empty basket, or a basket whose order is still open.
 * - While the basket's order is open (sending, retrying, a conflict, unknown)
 *   the basket is shown but locked. Accepted, or dismissed while unknown (it may
 *   have been booked), it clears; refused, cancelled or failed, it stays, unlocked
 *   (AC11, AC12, AC18).
 *
 * Components call only this, through `useBarController`; the property test
 * drives the same object. `view` is a new frozen object on every change, so
 * it serves `useSyncExternalStore` directly.
 */
import type { DrinkId, ExchangeState, Quote } from '../../exchange'
import type { OrderBody, OrderOutcome } from '../api/orders'
import { add, EMPTY, remove, type Basket } from './basket'
import { createHoldBuffer, isStale, type PressId } from './holdBuffer'
import { createOrderIntents, type Conflict, type OrderEntry } from './orderIntents'

export interface BarView {
  readonly displayed: Quote | null
  readonly latest: Quote | null
  readonly entries: readonly OrderEntry[]
  readonly headConflict: Conflict | null
  readonly basket: Basket
  /** The basket's order is open: the basket is shown, never edited (PD12). */
  readonly basketLocked: boolean
}

/** An entry in one of these states has settled; its basket is free again. */
const SETTLED = new Set(['accepted', 'failed', 'unavailable', 'cancelled', 'dismissed', 'refused'])

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
  /** A fresh `Idempotency-Key` (D-49: never Web Crypto's UUID, see `lib/idempotencyKey.ts`). */
  newKey(): string
}

export interface BarController {
  readonly view: BarView
  subscribe(listener: () => void): () => void
  press(id?: PressId): void
  release(id?: PressId): void
  /** One more of the drink in the basket (SD4); no request. */
  add(drinkId: DrinkId): void
  remove(drinkId: DrinkId): void
  /** "Leegmaken". */
  clear(): void
  /** "Afrekenen": the new entry's id, or `null` when it is refused. */
  checkout(): number | null
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
  let basket: Basket = EMPTY
  /** The id of the basket's order while it is open, else `null`. */
  let open: number | null = null

  function changed() {
    view = null
    for (const listener of listeners) listener()
  }

  /** The intents changed: let go of the basket's order once it has settled. */
  function settle() {
    if (open !== null) {
      const entry = intents.entries.find((e) => e.id === open)
      if (entry === undefined || SETTLED.has(entry.state)) {
        // A dismissed order may have been booked: a second checkout could pay twice.
        if (entry?.state === 'accepted' || entry?.state === 'dismissed') basket = EMPTY
        open = null
      }
    }
    changed()
  }

  function editBasket(next: Basket) {
    if (open !== null || next === basket) return
    basket = next
    changed()
  }

  const hold = createHoldBuffer({
    setTimeout: deps.setTimeout,
    clearTimeout: deps.clearTimeout,
    onChange: changed,
  })
  const intents = createOrderIntents({
    post: deps.post,
    newKey: deps.newKey,
    now: deps.now,
    setTimeout: deps.setTimeout,
    clearTimeout: deps.clearTimeout,
    onChange: settle,
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
        basket,
        basketLocked: open !== null,
      })
      return view
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    press: (id) => hold.pressStart(id),
    release: (id) => hold.pressEnd(id),
    add: (drinkId) => editBasket(add(basket, drinkId)),
    remove: (drinkId) => editBasket(remove(basket, drinkId)),
    clear: () => editBasket(EMPTY),
    checkout() {
      const displayed = hold.displayed
      if (displayed === null || isStale(hold.latest, deps.now())) return null
      if (intents.headConflict !== null || open !== null) return null
      const id = intents.create(displayed, basket, null)
      if (id !== null) {
        open = id
        changed()
      }
      return id
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

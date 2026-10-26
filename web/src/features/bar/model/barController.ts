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
 * - B-06 (SD4, SD13): `hold` keeps the scanned wallet -- the query that found it,
 *   its name and balance -- and `checkout` hands that query to the intent, so
 *   the order and its confirmation carry the wallet as scanned (AC5, AC11).
 * - While the basket's order is open (sending, retrying, a conflict, unknown)
 *   the basket and the wallet are shown but locked. Accepted, both clear (SD6);
 *   dismissed while unknown (it may have been booked), the basket clears.
 *   Refused, cancelled or failed, both stay, unlocked (AC11, AC12, AC18), but a
 *   `wallet_not_found` lets go of the wallet (AC12) and an
 *   `insufficient_balance` takes the server's balance for it (SD18).
 * - Letting go (B-06 SD6, PD15): "Andere wallet" (`otherWallet`) drops the
 *   wallet, "Annuleren" (`abandon`) both. While a wallet or a non-empty basket
 *   is held and no order of the basket is open, `WALLET_IDLE_MS` with no tap
 *   (`touch`, from the page's pointer and key downs) clears both.
 *
 * Components call only this, through `useBarController`; the property test
 * drives the same object. `view` is a new frozen object on every change, so
 * it serves `useSyncExternalStore` directly.
 */
import type { DrinkId, ExchangeState, Quote } from '../../exchange'
import type { OrderBody, OrderOutcome, WalletQuery } from '../api/orders'
import { add, EMPTY, remove, type Basket } from './basket'
import { WALLET_IDLE_MS } from './constants'
import { createHoldBuffer, isStale, type PressId } from './holdBuffer'
import { createOrderIntents, type Conflict, type OrderEntry, type Refusal } from './orderIntents'

/** A scanned wallet as the bar holds it (B-06 SD13): only its name and balance are shown. */
export interface HeldWallet {
  /** Exactly as scanned or typed; the order carries it, the server resolves it. */
  readonly query: WalletQuery
  readonly name: string
  readonly balance_cents: number
}

export interface BarView {
  readonly displayed: Quote | null
  readonly latest: Quote | null
  readonly entries: readonly OrderEntry[]
  readonly headConflict: Conflict | null
  readonly basket: Basket
  /** The basket's order is open: the basket and the wallet are shown, never edited (PD12). */
  readonly basketLocked: boolean
  readonly wallet: HeldWallet | null
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
  /** Hold a scanned wallet in place of any held one; refused while the basket is locked. */
  hold(wallet: HeldWallet): void
  /**
   * A fresh balance for the held wallet, looked up after a refund (AC18). Ignored once that
   * wallet is no longer the held one; it is no tap, so the idle wait does not restart.
   */
  updateBalance(query: WalletQuery, balanceCents: number): void
  /** "Andere wallet": let go of the wallet, keep the basket; refused while locked. */
  otherWallet(): void
  /** "Annuleren": let go of the wallet and the basket; refused while locked. */
  abandon(): void
  /** A tap anywhere on the page: the idle wait starts again (PD15). */
  touch(): void
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
  let wallet: HeldWallet | null = null
  /** The id of the basket's order while it is open, else `null`. */
  let open: number | null = null
  let idle: Id | null = null

  function changed() {
    view = null
    for (const listener of listeners) listener()
  }

  /** (Re)start the idle wait while something is held and no order of it is open (PD15). */
  function arm() {
    if (idle !== null) deps.clearTimeout(idle)
    idle = null
    if (open !== null || (wallet === null && basket.length === 0)) return
    idle = deps.setTimeout(() => {
      idle = null
      letGo(true)
    }, WALLET_IDLE_MS)
  }

  /** Drop the wallet, and the basket too when `all`; nothing while the basket is locked. */
  function letGo(all: boolean) {
    if (open !== null) return
    wallet = null
    if (all) basket = EMPTY
    arm()
    changed()
  }

  /** The intents changed: let go of the basket's order once it has settled. */
  function settle() {
    if (open !== null) {
      const entry = intents.entries.find((e) => e.id === open)
      if (entry === undefined || SETTLED.has(entry.state)) {
        // A dismissed order may have been booked: a second checkout could pay twice.
        if (entry?.state === 'accepted' || entry?.state === 'dismissed') basket = EMPTY
        if (entry?.state === 'accepted') wallet = null
        if (entry?.refusal != null) wallet = refused(wallet, entry.refusal)
        open = null
        arm()
      }
    }
    changed()
  }

  /** The held wallet after a wallet refusal (B-06 SD15, SD18; AC12). */
  function refused(held: HeldWallet | null, refusal: Refusal): HeldWallet | null {
    if (refusal.code === 'wallet_not_found') return null
    const balance = refusal.details.balance_cents
    if (held === null || refusal.code !== 'insufficient_balance' || typeof balance !== 'number') {
      return held
    }
    return Object.freeze({ ...held, balance_cents: balance })
  }

  function editBasket(next: Basket) {
    if (open !== null || next === basket) return
    basket = next
    arm()
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
        wallet,
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
    hold(next) {
      if (open !== null) return
      wallet = Object.freeze({ ...next })
      arm()
      changed()
    },
    updateBalance(query, balanceCents) {
      if (wallet === null || JSON.stringify(wallet.query) !== JSON.stringify(query)) return
      wallet = Object.freeze({ ...wallet, balance_cents: balanceCents })
      changed()
    },
    otherWallet: () => letGo(false),
    abandon: () => letGo(true),
    touch: () => arm(),
    checkout() {
      const displayed = hold.displayed
      if (displayed === null || isStale(hold.latest, deps.now())) return null
      if (intents.headConflict !== null || open !== null) return null
      const id = intents.create(displayed, basket, wallet?.query ?? null)
      if (id !== null) {
        open = id
        arm()
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
      if (idle !== null) deps.clearTimeout(idle)
      unsubscribe()
      hold.dispose()
      intents.dispose()
      listeners.clear()
    },
  }
}

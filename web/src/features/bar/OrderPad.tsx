/**
 * The order pad (Phase 5 SD5, SD11, SD18; B-06 SD4, SD5): one button per drink,
 * in the store's drink order, priced from the controller's **displayed** quote.
 * A tap adds one to the basket (B-06 SD4); the basket's lines have "−", and
 * "Leegmaken" empties it. "Afrekenen" sends the basket as one order at once.
 *
 * A pointer down or an Enter/Space keydown starts a press, and pointer up,
 * cancel, leave or keyup ends it; `click` is the tap (PD10). The press starts
 * before `click`, so a drink tap and "Afrekenen" both read a quote that is
 * already held. The pad never reads a price from the store -- only through the
 * controller's `Quote` -- and the basket's total is computed from that same
 * quote (`model/basket.ts`).
 *
 * Above the drinks, the wallet (B-06 SD4, SD13): the picker, or the held
 * wallet's name and balance. With one held the button reads "Afrekenen €T",
 * unless the total exceeds balance + "Rood staan tot", when it is disabled with
 * "Saldo €B — nog €X tekort" (SD18). With none, "Wallet verplicht" (SD1, SD17),
 * read from the store's `run` that a `config` message updates live, decides:
 * on, the button stays disabled with "Scan eerst een wallet"; off, it reads
 * "Afrekenen zonder wallet €T". The server judges both again when the order
 * arrives (SD15).
 *
 * Above `AGE_SHOW_MS` the age line and "Ververs" show (AC7); when the latest
 * quote is stale every button is disabled (AC8), as it is while a conflict is
 * open (AC14). While the basket's order is open, the basket is locked (PD12).
 * Socket state plays no part (SD11).
 */
import type { KeyboardEvent, PointerEvent } from 'react'
import { Button } from '../../components/ui/Button'
import { formatEuro } from '../../lib/format'
import { selectActiveDrinks, selectDrinks, useExchange } from '../exchange'
import { HeldWallet } from './HeldWallet'
import { lineCents, shortfallCents, totalCents } from './model/basket'
import { ageMs, isStale, showAge } from './model/holdBuffer'
import type { BarView } from './model/barController'
import type { BarActions } from './useBarController'
import { useNow } from './useNow'
import { WalletPicker } from './WalletPicker'
import { shortfallText } from './walletText'
import styles from './OrderPad.module.css'

export interface OrderPadProps {
  view: BarView
  actions: Pick<
    BarActions,
    | 'press'
    | 'release'
    | 'add'
    | 'remove'
    | 'clear'
    | 'hold'
    | 'otherWallet'
    | 'abandon'
    | 'checkout'
    | 'refresh'
  >
}

const PRESS_KEYS = new Set(['Enter', ' '])
/** The keyboard is one press; fingers are told apart by pointer id (AC5). */
const KEY_PRESS = 'key'

export function OrderPad({ view, actions }: OrderPadProps) {
  const drinks = useExchange(selectActiveDrinks)
  const allDrinks = useExchange(selectDrinks)
  const walletRequired = useExchange((s) => s.run?.wallet_required === true)
  const limit = useExchange((s) => s.run?.credit_limit_cents ?? 0)
  const now = useNow()
  const { displayed, latest, entries, headConflict, basket, basketLocked, wallet } = view
  const stale = isStale(latest, now)
  const disabled = stale || headConflict !== null
  const total = totalCents(basket, displayed)
  const nameOf = (id: number) => allDrinks.find((d) => d.drink_id === id)?.name ?? `#${id}`

  // Every pad button presses the hold, so the quote it reads is already held (SD4).
  const press = {
    onPointerDown: (e: PointerEvent) => actions.press(e.pointerId),
    onPointerUp: (e: PointerEvent) => actions.release(e.pointerId),
    onPointerCancel: (e: PointerEvent) => actions.release(e.pointerId),
    onPointerLeave: (e: PointerEvent) => actions.release(e.pointerId),
    onKeyDown: (e: KeyboardEvent) => {
      if (PRESS_KEYS.has(e.key)) actions.press(KEY_PRESS)
    },
    onKeyUp: (e: KeyboardEvent) => {
      if (PRESS_KEYS.has(e.key)) actions.release(KEY_PRESS)
    },
  }

  const totalText = total === null ? '—' : formatEuro(total)
  const shortfall =
    wallet === null || total === null ? 0 : shortfallCents(total, wallet.balance_cents, limit)
  let checkoutLabel = `Afrekenen zonder wallet ${totalText}`
  if (wallet !== null) {
    checkoutLabel =
      shortfall > 0 ? shortfallText(wallet.balance_cents, shortfall) : `Afrekenen ${totalText}`
  } else if (walletRequired) checkoutLabel = 'Scan eerst een wallet'
  const cannotCheckout =
    disabled ||
    basketLocked ||
    (wallet === null && walletRequired) ||
    shortfall > 0 ||
    basket.length === 0 ||
    total === null

  return (
    <div className={styles.pad} data-quote-version={displayed?.version}>
      {wallet === null ? (
        <WalletPicker disabled={basketLocked} onFound={actions.hold} />
      ) : (
        <HeldWallet
          wallet={wallet}
          locked={basketLocked}
          onOther={actions.otherWallet}
          onCancel={actions.abandon}
        />
      )}
      <div className={styles.grid} role="group" aria-label="Drankjes">
        {drinks.map(({ drink_id, name }) => {
          const price = displayed?.prices[drink_id]
          return (
            <Button
              key={drink_id}
              className={styles.drink}
              disabled={disabled || basketLocked || price === undefined}
              {...press}
              onClick={() => actions.add(drink_id)}
            >
              {name} — {price === undefined ? '—' : formatEuro(price)}
            </Button>
          )
        })}
      </div>
      {basket.length > 0 && (
        <div className={styles.basket}>
          <ul className={styles.lines} aria-label="Mandje">
            {basket.map((line) => {
              const cents = lineCents(line, displayed)
              const name = nameOf(line.drinkId)
              return (
                <li key={line.drinkId} className={styles.line}>
                  <span>
                    {line.qty}× {name} — {cents === null ? '—' : formatEuro(cents)}
                  </span>
                  <Button
                    aria-label={`Eén ${name} minder`}
                    disabled={basketLocked}
                    onClick={() => actions.remove(line.drinkId)}
                  >
                    −
                  </Button>
                </li>
              )
            })}
          </ul>
          <Button disabled={basketLocked} onClick={actions.clear}>
            Leegmaken
          </Button>
        </div>
      )}
      <Button
        className={styles.checkout}
        disabled={cannotCheckout}
        {...press}
        onClick={actions.checkout}
      >
        {checkoutLabel}
      </Button>
      {stale && <p className={styles.stale}>Geen actuele prijzen — wacht op verbinding</p>}
      {displayed !== null && showAge(displayed, now) && (
        <p className={styles.age}>
          Prijzen van {Math.floor(ageMs(displayed, now) / 1000)} s geleden{' '}
          <Button onClick={actions.refresh}>Ververs</Button>
        </p>
      )}
      {entries.length === 0 && basket.length === 0 && <p className={styles.status}>Klaar</p>}
    </div>
  )
}

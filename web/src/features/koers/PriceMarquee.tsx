/**
 * The price strip (`koers.html:667-682`): name, price and delta per active
 * drink (Phase 6 SD18), in the server's order, the row twice over so the loop is seamless. A pill is
 * tinted by the same direction as its tile (SD23).
 */
import { Marquee, type MarqueeItem } from '../../components/ui/Marquee'
import { deltaParts, formatEuro } from '../../lib/format'
import { pulseDirection, selectActiveDrinks, useExchange, type ExchangeState } from '../exchange'
import { DeltaIcon } from './DeltaIcon'
import styles from './KoersPage.module.css'

function row(state: ExchangeState, copy: number): MarqueeItem[] {
  return selectActiveDrinks(state).map(({ drink_id, name }) => {
    const price = state.prices[drink_id]?.price_cents
    const previous = state.prevPriceCents[drink_id]
    const direction = pulseDirection(state, drink_id)
    const delta =
      price === undefined || previous === undefined
        ? { direction: null, text: '—' }
        : deltaParts(previous, price)
    return {
      key: `${copy}-${drink_id}`,
      className: direction === null ? styles.tick : `${styles.tick} ${styles[direction]}`,
      parts: [
        { text: name, className: styles.tickName },
        { text: price === undefined ? '—' : formatEuro(price) },
        {
          text: delta.text,
          className: styles.change,
          icon: <DeltaIcon direction={delta.direction} />,
        },
      ],
    }
  })
}

export function PriceMarquee() {
  // Every price change re-renders the strip's text anyway; the animation is
  // untouched unless the drink count changes.
  const state = useExchange((s) => s)
  return <Marquee variant="loop" items={[...row(state, 0), ...row(state, 1)]} />
}

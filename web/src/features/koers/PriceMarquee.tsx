/**
 * The price strip (`koers.html:667-682`): name, price and delta per drink, in
 * the server's order, the row twice over so the loop is seamless. A pill is
 * tinted by the same direction as its tile (SD23).
 */
import { Marquee, type MarqueeItem } from '../../components/ui/Marquee'
import { deltaText, formatEuro } from '../../lib/format'
import { pulseDirection, useExchange, type ExchangeState } from '../exchange'
import styles from './KoersPage.module.css'

function row(state: ExchangeState, copy: number): MarqueeItem[] {
  return state.drinks.map(({ drink_id, name }) => {
    const price = state.prices[drink_id]?.price_cents
    const previous = state.prevPriceCents[drink_id]
    const direction = pulseDirection(state, drink_id)
    return {
      key: `${copy}-${drink_id}`,
      className: direction === null ? styles.tick : `${styles.tick} ${styles[direction]}`,
      parts: [
        { text: name, className: styles.tickName },
        { text: price === undefined ? '—' : formatEuro(price) },
        {
          text: price === undefined || previous === undefined ? '—' : deltaText(previous, price),
          className: styles.change,
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

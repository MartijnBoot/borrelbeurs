/**
 * The news strip (`koers.html:689-704`): level badge, time and text per
 * item, newest first, the pill tinted by its level. All three are text nodes,
 * so v1's `escHtml` has nothing left to do (AC32). With no news, "Geen
 * nieuws". It speeds up during a crash or bubble (`playbackRate`, AC33).
 */
import { Marquee, type MarqueeItem } from '../../components/ui/Marquee'
import { selectNews, useExchange } from '../exchange'
import styles from './KoersPage.module.css'

const TIME = new Intl.DateTimeFormat('nl-NL', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const EMPTY: MarqueeItem[] = [
  {
    key: 'empty',
    className: styles.newsItem,
    parts: [
      { text: 'info', className: styles.badge },
      { text: 'Geen nieuws', className: styles.newsText },
    ],
  },
]

export function NewsMarquee({ playbackRate }: { playbackRate: number }) {
  const news = useExchange(selectNews)
  const items: MarqueeItem[] =
    news.length === 0
      ? EMPTY
      : news.map((n) => ({
          key: String(n.news_id),
          // `info` has no tint of its own (`koers.html:66-68`)
          className: `${styles.newsItem} ${styles[n.level] ?? ''}`,
          parts: [
            { text: n.level, className: styles.badge },
            { text: TIME.format(n.ts_ms), className: styles.newsTime },
            { text: n.text, className: styles.newsText },
          ],
        }))
  return <Marquee variant="news" items={items} playbackRate={playbackRate} />
}

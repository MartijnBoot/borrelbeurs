/**
 * A full-width scrolling strip (`koers.html:37-50`), animated with the Web
 * Animations API rather than a CSS animation, because the animation's own
 * timeline is what keeps it from jumping (frontend-architecture.md,
 * "Marquees"):
 *
 * - New content with the same item count is just a React text update; the
 *   animation is untouched.
 * - A count change re-creates the animation and carries `currentTime` over
 *   from the old one -- never `performance.now()`, which a hover pause would
 *   have put out of step.
 * - `playbackRate` changes go through `updatePlaybackRate`.
 *
 * Every part is rendered as a text node (AC32). Hover pauses it (SD24).
 */
import { useEffect, useRef } from 'react'
import styles from './Marquee.module.css'

export interface MarqueePart {
  text: string
  className?: string
}

export interface MarqueeItem {
  key: string
  className?: string
  parts: readonly MarqueePart[]
}

export type MarqueeVariant = 'loop' | 'news'

/** `scroll`: a doubled row moves by half its width; `scroll-news`: across the screen. */
const KEYFRAMES: Record<MarqueeVariant, Keyframe[]> = {
  loop: [{ transform: 'translateX(0)' }, { transform: 'translateX(-50%)' }],
  news: [{ transform: 'translateX(100vw)' }, { transform: 'translateX(-100%)' }],
}

const DURATION_MS = 30_000

export interface MarqueeProps {
  items: readonly MarqueeItem[]
  variant: MarqueeVariant
  playbackRate?: number
}

export function Marquee({ items, variant, playbackRate = 1 }: MarqueeProps) {
  const track = useRef<HTMLDivElement>(null)
  const animation = useRef<Animation | null>(null)
  const rate = useRef(playbackRate)
  const carried = useRef<CSSNumberish | null>(null)
  const count = items.length

  // Declared first, so a new animation below starts at the current rate.
  useEffect(() => {
    rate.current = playbackRate
    animation.current?.updatePlaybackRate(playbackRate)
  }, [playbackRate])

  useEffect(() => {
    const element = track.current
    if (element === null) return
    const next = element.animate(KEYFRAMES[variant], {
      duration: DURATION_MS,
      iterations: Infinity,
      easing: 'linear',
    })
    if (carried.current !== null) next.currentTime = carried.current
    next.playbackRate = rate.current
    animation.current = next
    return () => {
      carried.current = next.currentTime
      next.cancel()
      animation.current = null
    }
  }, [count, variant])

  return (
    <div
      className={variant === 'news' ? `${styles.wrap} ${styles.news}` : styles.wrap}
      onMouseEnter={() => animation.current?.pause()}
      onMouseLeave={() => animation.current?.play()}
    >
      <div ref={track} className={styles.track}>
        {items.map((item) => (
          <span key={item.key} className={item.className}>
            {item.parts.map((part, i) => (
              <span key={i} className={part.className}>
                {part.text}
              </span>
            ))}
          </span>
        ))}
      </div>
    </div>
  )
}

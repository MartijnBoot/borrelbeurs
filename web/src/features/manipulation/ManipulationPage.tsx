/**
 * The manipulation page (`/manipulation`, Phase 6 SD20): v1's sections 📰
 * Nieuws, 💥 Market events and ⚡ Price jump for bar and admin, and ⏳ Idle for
 * admin only (D-44). Every section reads the store, so a broadcast re-renders
 * it -- v1's drink select stayed stale (`manipulation.html:405-416`).
 *
 * `canEditIdle` is the session's role, passed in by `routes.tsx` (PD13). It
 * also decides the price jump's bounds hint, whose `GET config` is admin-only.
 */
import type { ReactNode } from 'react'
import { IdleSection } from './IdleSection'
import { MarketEventsSection } from './MarketEventsSection'
import { NewsSection } from './NewsSection'
import { PriceJumpSection } from './PriceJumpSection'
import styles from './ManipulationPage.module.css'

export function ManipulationPage({ canEditIdle }: { canEditIdle: boolean }) {
  return (
    <div className={styles.page}>
      <Section id="nieuws" title="📰 Nieuws">
        <NewsSection />
      </Section>
      <Section id="events" title="💥 Market events">
        <MarketEventsSection />
      </Section>
      <Section id="jump" title="⚡ Price jump">
        <PriceJumpSection showBounds={canEditIdle} />
      </Section>
      {canEditIdle && (
        <Section id="idle" title="⏳ Idle">
          <IdleSection />
        </Section>
      )}
    </div>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className={styles.section} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  )
}

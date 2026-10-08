/**
 * `/settings`' frame (Phase 6 SD25): every section under its own heading and
 * anchor, in v1's sidebar order, with `MobileSectionNav` beside them -- or above
 * them, as one select, on a narrow screen.
 */
import type { ReactNode } from 'react'
import { MobileSectionNav } from '../../components/ui/MobileSectionNav'
import styles from './settings.module.css'

export interface SettingsSection {
  id: string
  label: string
  content: ReactNode
}

export function SettingsLayout({ sections }: { sections: readonly SettingsSection[] }) {
  return (
    <div className={styles.layout}>
      <div className={styles.nav}>
        <MobileSectionNav sections={sections} />
      </div>
      <div className={styles.sections}>
        {sections.map((section) => (
          <section
            key={section.id}
            id={section.id}
            aria-labelledby={`${section.id}-title`}
            className={styles.section}
          >
            <h2 id={`${section.id}-title`}>{section.label}</h2>
            {section.content}
          </section>
        ))}
      </div>
    </div>
  )
}

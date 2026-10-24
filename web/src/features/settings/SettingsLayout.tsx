/**
 * `/settings`' frame (Phase 6 SD25): every section under its own heading and
 * anchor, in v1's sidebar order, with `MobileSectionNav` beside them -- or above
 * them, as one select, on a narrow screen. A section's pixel icon goes before
 * its name in the heading (B-02 SD4).
 */
import type { ReactNode } from 'react'
import { MobileSectionNav } from '../../components/ui/MobileSectionNav'
import { PixelIcon, type PixelIconName } from '../../components/ui/PixelIcon'
import styles from './settings.module.css'

export interface SettingsSection {
  id: string
  label: string
  icon?: PixelIconName
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
            <h2 id={`${section.id}-title`}>
              {section.icon && <PixelIcon name={section.icon} />}
              {section.label}
            </h2>
            {section.content}
          </section>
        ))}
      </div>
    </div>
  )
}

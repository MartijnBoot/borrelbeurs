/**
 * The settings sections' navigation (Phase 6 SD25): in-page links, or, on a
 * narrow screen, one select that scrolls to the chosen section.
 */
import { useMediaQuery } from '../../lib/useMediaQuery'
import styles from './MobileSectionNav.module.css'
import { Select } from './Select'

export const NARROW_NAV = '(max-width: 800px)'

export interface Section {
  id: string
  label: string
}

export function MobileSectionNav({ sections }: { sections: readonly Section[] }) {
  const narrow = useMediaQuery(NARROW_NAV)
  if (narrow) {
    return (
      <Select
        label="Sectie"
        value={sections[0]?.id ?? ''}
        options={sections.map((s) => ({ value: s.id, label: s.label }))}
        onChange={(id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })}
      />
    )
  }
  return (
    <nav aria-label="Secties" className={styles.nav}>
      {sections.map((s) => (
        <a key={s.id} href={`#${s.id}`} className={styles.link}>
          {s.label}
        </a>
      ))}
    </nav>
  )
}

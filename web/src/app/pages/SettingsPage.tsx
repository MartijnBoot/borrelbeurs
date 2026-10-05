import { ThemeSection } from '../../features/theme'
import { Placeholder } from './Placeholder'

/**
 * `/settings` (SD10, PD13): the theme section, then SD4's placeholder for the
 * rest. Composed here in the app layer because a `features/settings` could
 * not import `features/theme` (sibling isolation); Phase 6 moves it.
 */
export function SettingsPage() {
  return (
    <>
      <ThemeSection />
      <Placeholder />
    </>
  )
}

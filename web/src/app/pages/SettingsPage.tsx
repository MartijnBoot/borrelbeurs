import { KeysSection } from '../../features/keys'
import {
  BorrelSection,
  BoundsSection,
  DemandSection,
  DrinksSection,
  GlobalSection,
  NotYet,
  type SettingsSection,
  SettingsLayout,
  SystemSection,
  ThemeSection,
} from '../../features/settings'

/**
 * `/settings` (Phase 6 SD25, PD13): v1's sidebar sections, in its order.
 * Composed here in the app layer, because `features/keys` and
 * `features/settings` may not import each other (sibling isolation).
 */
const SECTIONS: readonly SettingsSection[] = [
  { id: 'borrel', label: 'Borrel', content: <BorrelSection /> },
  { id: 'systeem', label: '🧹 Systeemacties', content: <SystemSection /> },
  { id: 'globaal', label: '⚙️ Globale instellingen', content: <GlobalSection /> },
  { id: 'kleuren', label: '🎨 Kleurenschema', content: <ThemeSection /> },
  { id: 'afbeeldingen', label: '🖼️ Afbeeldingen', content: <NotYet /> },
  { id: 'drankjes', label: '🥤 Drankjes beheren', content: <DrinksSection /> },
  { id: 'prijzen', label: '🔒 Min/Max/Startprijs', content: <BoundsSection /> },
  { id: 'vraag', label: '📈 Vraag/Aanbod', content: <DemandSection /> },
  { id: 'sleutels', label: '🔑 Toegangssleutels', content: <KeysSection /> },
]

export function SettingsPage() {
  return <SettingsLayout sections={SECTIONS} />
}

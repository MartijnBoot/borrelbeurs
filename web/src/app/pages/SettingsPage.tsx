import { KeysSection } from '../../features/keys'
import {
  BorrelSection,
  BoundsSection,
  DemandSection,
  DrinksSection,
  GlobalSection,
  ImagesSection,
  type SettingsSection,
  SettingsLayout,
  SystemSection,
  ThemeEditor,
  ThemeSection,
} from '../../features/settings'

/**
 * `/settings` (Phase 6 SD25, PD13): v1's sidebar sections, in its order.
 * Composed here in the app layer, because `features/keys` and
 * `features/settings` may not import each other (sibling isolation).
 */
const SECTIONS: readonly SettingsSection[] = [
  { id: 'borrel', label: 'Borrel', content: <BorrelSection /> },
  { id: 'systeem', label: 'Systeemacties', icon: 'broom', content: <SystemSection /> },
  { id: 'globaal', label: 'Globale instellingen', icon: 'gear', content: <GlobalSection /> },
  {
    id: 'kleuren',
    label: 'Kleurenschema',
    icon: 'palette',
    content: (
      <>
        <ThemeSection />
        <ThemeEditor />
      </>
    ),
  },
  { id: 'afbeeldingen', label: 'Afbeeldingen', icon: 'picture', content: <ImagesSection /> },
  { id: 'drankjes', label: 'Drankjes beheren', icon: 'cup', content: <DrinksSection /> },
  { id: 'prijzen', label: 'Min/Max/Startprijs', icon: 'padlock', content: <BoundsSection /> },
  { id: 'vraag', label: 'Vraag/Aanbod', icon: 'chart', content: <DemandSection /> },
  { id: 'sleutels', label: 'Toegangssleutels', icon: 'key', content: <KeysSection /> },
]

export function SettingsPage() {
  return <SettingsLayout sections={SECTIONS} />
}

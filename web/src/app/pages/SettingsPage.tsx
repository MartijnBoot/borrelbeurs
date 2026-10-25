import { KeysSection } from '../../features/keys'
import {
  BorrelSection,
  BoundsSection,
  DemandSection,
  DrinksSection,
  GlobalSection,
  ImagesSection,
  ProfilesSection,
  type SettingsSection,
  SettingsLayout,
  SystemSection,
  ThemeEditor,
  ThemeSection,
} from '../../features/settings'
import { WalletsSection } from '../../features/wallets'
import { settingNames } from './settingNames'

/**
 * `/settings` (Phase 6 SD25, PD13): v1's sidebar sections, in its order.
 * Composed here in the app layer, because `features/keys`, `features/wallets`
 * and `features/settings` may not import each other (sibling isolation).
 */
const SECTIONS: readonly SettingsSection[] = [
  { id: 'borrel', label: 'Borrel', content: <BorrelSection names={settingNames} /> },
  { id: 'systeem', label: 'Systeemacties', icon: 'broom', content: <SystemSection /> },
  { id: 'globaal', label: 'Globale instellingen', icon: 'gear', content: <GlobalSection /> },
  {
    id: 'profielen',
    label: 'Profielen',
    icon: 'floppy',
    content: <ProfilesSection names={settingNames} />,
  },
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
  // B-05 SD16, SD25: after Toegangssleutels, with the approved `wallet` icon (T14).
  { id: 'wallets', label: 'Wallets', icon: 'wallet', content: <WalletsSection /> },
]

export function SettingsPage() {
  return <SettingsLayout sections={SECTIONS} />
}

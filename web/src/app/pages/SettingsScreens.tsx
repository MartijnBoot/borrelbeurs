/**
 * The three settings screens (B-12 SD1, SD3, SD8, SD12): Spelopzet
 * (`/settings/spel`) for the night, Mensen en wallets (`/settings/wallets`)
 * for the players, and Beheer (`/settings/beheer`) for the system, Systeemacties
 * last. Each is one `SettingsScreen`: "← Instellingen" to the landing above
 * its own sections. Composed here in the app layer, as the one page was,
 * because `features/keys`, `features/wallets` and `features/settings` may not
 * import each other (sibling isolation). The section ids are the old page's.
 */
import { Link } from 'react-router'
import { KeysSection } from '../../features/keys'
import {
  BorrelSection,
  BoundsSection,
  DemandSection,
  DrinksSection,
  GlobalSection,
  ImagesSection,
  PriceStepSection,
  ProfilesSection,
  type SettingsSection,
  SettingsLayout,
  SystemSection,
  ThemeEditor,
  ThemeSection,
} from '../../features/settings'
import { WalletsSection } from '../../features/wallets'
import styles from './pages.module.css'
import { settingNames } from './settingNames'

const SPELOPZET: readonly SettingsSection[] = [
  { id: 'borrel', label: 'Borrel', content: <BorrelSection names={settingNames} /> },
  {
    id: 'profielen',
    label: 'Profielen',
    icon: 'floppy',
    content: <ProfilesSection names={settingNames} />,
  },
  { id: 'drankjes', label: 'Drankjes beheren', icon: 'cup', content: <DrinksSection /> },
  // SD4, SD12: Prijsstap above the bounds it constrains, under Min/Max/Startprijs's icon.
  {
    id: 'prijzen',
    label: 'Prijzen',
    icon: 'padlock',
    content: (
      <>
        <PriceStepSection />
        <BoundsSection />
      </>
    ),
  },
  { id: 'vraag', label: 'Vraag/Aanbod', icon: 'chart', content: <DemandSection /> },
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
]

const WALLETS: readonly SettingsSection[] = [
  { id: 'wallets', label: 'Wallets', icon: 'wallet', content: <WalletsSection /> },
]

const BEHEER: readonly SettingsSection[] = [
  { id: 'globaal', label: 'Globale instellingen', icon: 'gear', content: <GlobalSection /> },
  { id: 'sleutels', label: 'Toegangssleutels', icon: 'key', content: <KeysSection /> },
  { id: 'systeem', label: 'Systeemacties', icon: 'broom', content: <SystemSection /> },
]

/** One screen (PD8): the way back to the landing, then its sections. */
export function SettingsScreen({ sections }: { sections: readonly SettingsSection[] }) {
  return (
    <>
      <Link to="/settings" className={styles.back}>
        ← Instellingen
      </Link>
      <SettingsLayout sections={sections} />
    </>
  )
}

export function SpelopzetPage() {
  return <SettingsScreen sections={SPELOPZET} />
}

export function WalletsScreenPage() {
  return <SettingsScreen sections={WALLETS} />
}

export function BeheerPage() {
  return <SettingsScreen sections={BEHEER} />
}

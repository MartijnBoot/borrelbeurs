/**
 * `/settings`, the landing page (B-12 SD2, SD10, SD15, PD7): one status line
 * for the current run, from the same source as the Borrel section, then one
 * tile per settings screen the session's `allowed_routes` holds, in SD3's
 * order. It holds no settings and no section, so an old `/settings#borrel`
 * link opens it and scrolls nowhere (SD14). The screens are in
 * `SettingsScreens.tsx`.
 *
 * B-13 SD14: the status line reads `GET /api/runs/current`, which only a session
 * holding Spelopzet may call, so it is mounted only for one: the kassa sees its
 * one tile and asks for no run.
 */
import { Link } from 'react-router'
import { useSession } from '../../features/auth'
import { type CurrentRun, useCurrentRun } from '../../features/settings'
import styles from './pages.module.css'

const SCREENS = [
  [
    '/settings/spel',
    'Spelopzet',
    'Borrel, profielen, drankjes, prijzen, vraag/aanbod, kleuren, afbeeldingen.',
  ],
  [
    '/settings/wallets',
    'Mensen en wallets',
    'Betalen, aanmeldcode, bewaartermijnen, alle wallets.',
  ],
  [
    '/settings/beheer',
    'Beheer',
    'Globale instellingen, vraag/aanbod, toegangssleutels, systeemacties.',
  ],
] as const

const RUN_STATUS: Readonly<Record<CurrentRun['status'], string>> = {
  draft: 'concept',
  live: 'live',
  ended: 'afgelopen',
}

function statusLine(run: CurrentRun | null | undefined, failed: boolean): string {
  if (failed) return 'Borrel: onbekend'
  if (run === undefined) return 'Laden…'
  if (run === null) return 'Geen actieve borrel'
  return `Borrel: ${run.name} (${RUN_STATUS[run.status]})`
}

function RunStatus() {
  const { run, failed } = useCurrentRun()
  return <p className={styles.runStatus}>{statusLine(run, failed)}</p>
}

export function SettingsPage() {
  const { session } = useSession()
  const allowed = session.status === 'ready' ? session.me.allowed_routes : []
  return (
    <div className={styles.landing}>
      {allowed.includes('/settings/spel') && <RunStatus />}
      <div className={styles.tiles}>
        {SCREENS.filter(([path]) => allowed.includes(path)).map(([path, name, line]) => (
          <Link key={path} to={path} className={styles.tile}>
            <h2>{name}</h2>
            <p>{line}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}

/**
 * Home (`/`, Phase 6 SD31; AC41, AC25): v1's four tiles and a "Status" panel.
 *
 * - **Tiles:** v1's titles and blurbs (`home.html`), corrected: drinks and
 *   shutdown moved to settings, so the manipulation blurb drops them.
 * - **Status:**
 *   - this browser's socket (Verbonden / Verbinden… / Offline) and the age of
 *     its last frame, from the store's `lastFrameAt` (PD14);
 *   - the run from `GET /api/runs/current`, with the store's `quote.version`
 *     and `/healthz`'s `last_tick_age_ms`, or "Geen actieve borrel";
 *   - server health, `/healthz` every 5 s;
 *   - connections per role, `/api/admin/connections` every 5 s. With no display
 *     connected during a live run: "Koersbord niet verbonden", in `--warn`.
 *
 * Every fetch's rejection is caught, and polling stops on unmount.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { z } from 'zod'
import { type DotStatus, StatusDot } from '../../components/ui/StatusDot'
import { HttpError, request } from '../../lib/http'
import { useExchange } from '../exchange'
import styles from './HomePage.module.css'

const POLL_MS = 5_000

const TILES = [
  ['/koers', 'Live koersbord', 'Bekijk live prijzen en grafiek.', 'Open koers'],
  ['/bar', 'Bar', 'Snel bestellingen plaatsen.', 'Open bar'],
  [
    '/settings',
    'Instellingen',
    'Globale instellingen, grenzen, vraag/aanbod, drankjes, afsluiten.',
    'Open instellingen',
  ],
  ['/manipulation', 'Spel mechanica', 'Price jumps, nieuws, idle, reset.', 'Open spel mechanica'],
] as const

const CurrentRun = z.object({
  run_id: z.number().int(),
  name: z.string(),
  status: z.enum(['draft', 'live', 'ended']),
})
type CurrentRun = z.infer<typeof CurrentRun>

const Health = z.object({ status: z.string(), last_tick_age_ms: z.number().nullable() })
type Health = z.infer<typeof Health> | 'stale' | 'unreachable'

const Connections = z.array(z.object({ role: z.enum(['display', 'bar', 'admin']) }))

const ROLES = [
  ['display', 'Scherm'],
  ['bar', 'Bar'],
  ['admin', 'Beheer'],
] as const

const RUN_STATUS: Readonly<Record<CurrentRun['status'], string>> = {
  draft: 'concept',
  live: 'live',
  ended: 'afgelopen',
}

const SOCKET: Readonly<Record<string, [DotStatus, string]>> = {
  open: ['ok', 'Verbonden'],
  connecting: ['warn', 'Verbinden…'],
  offline: ['down', 'Offline'],
}

const SECONDS = new Intl.NumberFormat('nl-NL', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})
const seconds = (ms: number) => `${SECONDS.format(ms / 1000)} s`

/** Calls `load` now and every `POLL_MS` until unmount; `load` catches its own failures. */
function usePoll(load: () => Promise<void>) {
  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), POLL_MS)
    return () => clearInterval(timer)
  }, [load])
}

/** `undefined` while loading, `null` without a current run. */
function useCurrentRun(): CurrentRun | null | undefined {
  const [run, setRun] = useState<CurrentRun | null | undefined>(undefined)
  const liveRunId = useExchange((s) => s.run?.run_id ?? null)
  useEffect(() => {
    let current = true
    request('GET', '/api/runs/current', { schema: CurrentRun }).then(
      (found) => current && setRun(found),
      () => current && setRun(null),
    )
    return () => {
      current = false
    }
  }, [liveRunId])
  return run
}

const loadHealth = (set: (health: Health) => void) => () =>
  request('GET', '/healthz', { schema: Health }).then(set, (error: unknown) =>
    set(error instanceof HttpError && error.status === 503 ? 'stale' : 'unreachable'),
  )

const loadConnections = (set: (roles: string[] | null) => void) => () =>
  request('GET', '/api/admin/connections', { schema: Connections }).then(
    (list) => set(list.map((c) => c.role)),
    () => set(null),
  )

export function HomePage() {
  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Welkom bij de Beurs Borrel</h1>
      <div className={styles.grid}>
        {TILES.map(([href, title, blurb, cta]) => (
          <Link key={href} to={href} className={styles.tile}>
            <h2>{title}</h2>
            <p>{blurb}</p>
            <span className={styles.cta}>{cta}</span>
          </Link>
        ))}
      </div>
      <StatusPanel />
    </div>
  )
}

function StatusPanel() {
  const socket = useExchange((s) => s.status)
  const lastFrameAt = useExchange((s) => s.lastFrameAt)
  const version = useExchange((s) => s.quote?.version ?? null)
  const run = useCurrentRun()
  const [health, setHealth] = useState<Health | null>(null)
  const [roles, setRoles] = useState<string[] | null>(null)
  const [now, setNow] = useState(() => performance.now())

  const [pollHealth] = useState(() => loadHealth(setHealth))
  const [pollConnections] = useState(() => loadConnections(setRoles))
  usePoll(pollHealth)
  usePoll(pollConnections)
  useEffect(() => {
    const timer = setInterval(() => setNow(performance.now()), 1_000)
    return () => clearInterval(timer)
  }, [])

  const [socketDot, socketText] = SOCKET[socket]
  const live = run?.status === 'live'
  const tickAge = typeof health === 'object' && health !== null ? health.last_tick_age_ms : null
  const displays = roles?.filter((role) => role === 'display').length ?? 0

  return (
    <section className={styles.status} aria-labelledby="status-title">
      <h2 id="status-title">Status</h2>
      <ul className={styles.list}>
        <li>
          <StatusDot status={socketDot} label={socketText} />
          {socketText}
          {lastFrameAt !== null &&
            ` — laatste bericht ${seconds(Math.max(0, now - lastFrameAt))} geleden`}
        </li>
        <li>
          {run === undefined ? (
            'Laden…'
          ) : run === null ? (
            <>
              <StatusDot status="warn" label="Geen borrel" />
              Geen actieve borrel
            </>
          ) : (
            <>
              <StatusDot status={live ? 'ok' : 'warn'} label={RUN_STATUS[run.status]} />
              {`${run.name} (${RUN_STATUS[run.status]})`}
              {live && version !== null && ` — versie ${version}`}
              {live && tickAge !== null && ` — laatste tick ${seconds(tickAge)} geleden`}
            </>
          )}
        </li>
        <li>
          <HealthLine health={health} />
        </li>
        <li>
          {roles === null
            ? 'Verbindingen: onbekend'
            : `Verbindingen — ${ROLES.map(
                ([role, label]) => `${label}: ${roles.filter((r) => r === role).length}`,
              ).join(', ')}`}
        </li>
      </ul>
      {live && roles !== null && displays === 0 && (
        <p className={styles.warn} role="alert">
          Koersbord niet verbonden
        </p>
      )}
    </section>
  )
}

function HealthLine({ health }: { health: Health | null }) {
  if (health === null) return <>Server: …</>
  if (health === 'unreachable') {
    return (
      <>
        <StatusDot status="down" label="Server onbereikbaar" />
        Server: onbereikbaar
      </>
    )
  }
  if (health === 'stale') {
    return (
      <>
        <StatusDot status="warn" label="Server traag" />
        Server: ticker loopt achter
      </>
    )
  }
  return (
    <>
      <StatusDot status="ok" label="Server ok" />
      Server: ok
    </>
  )
}

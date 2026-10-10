/**
 * The run list (Phase 7 SD10, PD12): one row per run, newest first, with its
 * start, end, duration and totals in euros. A live run's duration is "loopt",
 * a draft's "—". Each row picks the run for detail, as A or B for compare, or
 * -- unless live -- for delete.
 */
import { Button } from '../../components/ui/Button'
import { formatEuro } from '../../lib/format'
import styles from './analytics.module.css'
import type { AnalyticsRun } from './api/runs'

const STATUS = { draft: 'Concept', live: 'Live', ended: 'Afgelopen' } as const
const WHEN = new Intl.DateTimeFormat('nl-NL', { dateStyle: 'short', timeStyle: 'short' })

const when = (ms: number | null) => (ms === null ? '—' : WHEN.format(ms))

/** `9_000_000` → `"2:30"`: hours and minutes. */
function duration(run: AnalyticsRun): string {
  if (run.status === 'live') return 'loopt'
  if (run.duration_ms === null) return '—'
  const minutes = Math.floor(run.duration_ms / 60_000)
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`
}

export interface RunListProps {
  runs: readonly AnalyticsRun[]
  detailId: number | null
  compareA: number | null
  compareB: number | null
  onDetail(runId: number): void
  onCompareA(runId: number): void
  onCompareB(runId: number): void
  onDelete(run: AnalyticsRun): void
}

export function RunList(props: RunListProps) {
  const { runs, detailId, compareA, compareB } = props
  if (runs.length === 0) return <p className={styles.muted}>Nog geen borrels</p>
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Naam</th>
            <th>Status</th>
            <th>Start</th>
            <th>Einde</th>
            <th>Duur</th>
            <th className={styles.number}>Omzet</th>
            <th className={styles.number}>Omzet tegen barprijs</th>
            <th className={styles.number}>Aantal</th>
            <th>Vergelijk</th>
            <th>Acties</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id} className={run.run_id === detailId ? styles.selected : undefined}>
              <td>{run.name}</td>
              <td>{STATUS[run.status]}</td>
              <td>{when(run.t0_ms)}</td>
              <td>{when(run.ended_at_ms)}</td>
              <td>{duration(run)}</td>
              <td className={styles.number}>{formatEuro(run.revenue_cents)}</td>
              <td className={styles.number}>{formatEuro(run.bar_price_total_cents)}</td>
              <td className={styles.number}>{run.qty}</td>
              <td>
                <span className={styles.actions}>
                  <label>
                    <input
                      type="radio"
                      name="compare-a"
                      checked={run.run_id === compareA}
                      onChange={() => props.onCompareA(run.run_id)}
                    />
                    A
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="compare-b"
                      checked={run.run_id === compareB}
                      onChange={() => props.onCompareB(run.run_id)}
                    />
                    B
                  </label>
                </span>
              </td>
              <td>
                <span className={styles.actions}>
                  <Button onClick={() => props.onDetail(run.run_id)}>Details</Button>
                  {run.status !== 'live' && (
                    <Button onClick={() => props.onDelete(run)}>Verwijderen</Button>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

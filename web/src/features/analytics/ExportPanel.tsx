/**
 * A run's exports (Phase 7 SD6, SD12; AC7, AC17, AC20): kind, status, time and
 * size per export, newest first, and "Exporteer (xlsx)". While any export is
 * `queued` or `running` it is fetched again every 2 s (SD12: no WebSocket
 * message), and the polling stops once none is, or on unmount. A `done` export
 * is a plain download link; a `failed` one shows its error and "Opnieuw".
 */
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { HttpError } from '../../lib/http'
import styles from './analytics.module.css'
import { type ExportData, fileUrl, getExport, listExports, requestExport } from './api/exports'

const POLL_MS = 2_000
const KIND = { manual: 'Export', final: 'Eindexport' } as const
const STATUS = {
  queued: 'In de wachtrij',
  running: 'Bezig',
  done: 'Klaar',
  failed: 'Mislukt',
} as const
const ERRORS: Readonly<Record<string, string>> = { onderbroken: 'Onderbroken' }
const WHEN = new Intl.DateTimeFormat('nl-NL', { dateStyle: 'short', timeStyle: 'short' })

const inFlight = (e: ExportData) => e.status === 'queued' || e.status === 'running'
const size = (bytes: number | null) => (bytes === null ? '—' : `${Math.ceil(bytes / 1024)} kB`)

function failureText(error: unknown): string {
  if (error instanceof HttpError && error.code === 'export_busy') {
    return 'Er loopt al een export. Probeer het zo opnieuw.'
  }
  return 'Verbindingsfout. Probeer opnieuw.'
}

/** `rows` with each of `updates` put in place by id, a new one first. */
function withUpdates(rows: readonly ExportData[], updates: readonly ExportData[]): ExportData[] {
  const byId = new Map(updates.map((row) => [row.export_id, row]))
  const fresh = updates.filter((row) => !rows.some((old) => old.export_id === row.export_id))
  return [...fresh, ...rows.map((row) => byId.get(row.export_id) ?? row)]
}

export interface ExportPanelProps {
  runId: number
}

export function ExportPanel({ runId }: ExportPanelProps) {
  const [loaded, setLoaded] = useState<{ runId: number; rows: ExportData[] } | null>(null)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [polls, setPolls] = useState(0)

  useEffect(() => {
    let current = true
    listExports(runId).then(
      (rows) => {
        if (!current) return
        setLoaded({ runId, rows })
        setFailed(false)
      },
      () => current && setFailed(true),
    )
    return () => {
      current = false
    }
  }, [runId])

  const rows = loaded?.runId === runId ? loaded.rows : undefined
  const waiting = (rows ?? []).filter(inFlight).map((row) => row.export_id)
  const waitingKey = waiting.join(',')

  useEffect(() => {
    if (waitingKey === '') return
    let current = true
    const ids = waitingKey.split(',').map(Number)
    const timer = setTimeout(() => {
      Promise.all(ids.map(getExport)).then(
        (updates) => {
          if (!current) return
          setLoaded((old) => old && { ...old, rows: withUpdates(old.rows, updates) })
          setPolls((n) => n + 1)
          if (updates.some((row) => !inFlight(row))) {
            // A finished build may have pruned an older export (AC24), and a close
            // may have queued a final one meanwhile: the list itself has moved.
            listExports(runId).then(
              (rows) => setLoaded((old) => (old?.runId === runId ? { runId, rows } : old)),
              () => {}, // the merged rows stand
            )
          }
        },
        () => current && setPolls((n) => n + 1), // try again on the next beat
      )
    }, POLL_MS)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [runId, waitingKey, polls])

  async function exportNow() {
    try {
      const row = await requestExport(runId)
      setLoaded((old) => ({
        runId,
        rows: withUpdates(old?.runId === runId ? old.rows : [], [row]),
      }))
      setError(null)
    } catch (failure) {
      setError(failureText(failure))
    }
  }

  return (
    <div>
      <div className={styles.actions}>
        <Button onClick={() => void exportNow()}>Exporteer (xlsx)</Button>
      </div>
      {failed && <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>}
      {rows?.length === 0 && <p className={styles.muted}>Nog geen exports</p>}
      {rows !== undefined && rows.length > 0 && (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Soort</th>
                <th>Status</th>
                <th>Aangevraagd</th>
                <th className={styles.number}>Grootte</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.export_id}>
                  <td>{KIND[row.kind]}</td>
                  <td>{STATUS[row.status]}</td>
                  <td>{WHEN.format(row.created_at_ms)}</td>
                  <td className={styles.number}>{size(row.bytes)}</td>
                  <td>
                    {row.status === 'done' && (
                      <a href={fileUrl(row.export_id)} download>
                        Download
                      </a>
                    )}
                    {row.status === 'failed' && (
                      <span className={styles.actions}>
                        <span>{ERRORS[row.error ?? ''] ?? row.error ?? 'Onbekende fout'}</span>
                        <Button onClick={() => void exportNow()}>Opnieuw</Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

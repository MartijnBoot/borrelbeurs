/**
 * `/analytics` (Phase 7 SD10; AC8, AC32, AC33): one admin page. The run list on
 * top; below it the chosen run's detail and exports, and the comparison of the
 * runs picked as A and B. The selection lives here. Deleting a run asks for its
 * name to be typed (`ConfirmDialog`), then reloads the list and drops the run
 * from the selection.
 */
import { useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { HttpError } from '../../lib/http'
import styles from './analytics.module.css'
import { type AnalyticsRun, deleteRun, fetchRuns } from './api/runs'
import { CompareView } from './CompareView'
import { ExportPanel } from './ExportPanel'
import { RunDetail } from './RunDetail'
import { RunList } from './RunList'

const REFUSALS: Readonly<Record<string, string>> = {
  run_live: 'Sluit de borrel eerst af.',
  name_mismatch: 'Naam komt niet overeen.',
  run_not_found: 'Deze borrel bestaat niet meer.',
}

function failureText(error: unknown): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  return 'Verbindingsfout. Probeer opnieuw.'
}

export function AnalyticsPage() {
  const [runs, setRuns] = useState<AnalyticsRun[] | undefined>(undefined)
  const [failed, setFailed] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [compareA, setCompareA] = useState<number | null>(null)
  const [compareB, setCompareB] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<AnalyticsRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      fetchRuns().then(
        (list) => {
          setRuns(list)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function remove(run: AnalyticsRun) {
    setDeleting(null)
    try {
      await deleteRun(run.run_id, run.name)
      setError(null)
      const gone = (id: number | null) => (id === run.run_id ? null : id)
      setDetailId(gone)
      setCompareA(gone)
      setCompareB(gone)
    } catch (failure) {
      setError(failureText(failure))
    }
    await load()
  }

  const detail = runs?.find((run) => run.run_id === detailId)

  return (
    <div className={styles.page}>
      <section className={styles.section} aria-label="Borrels">
        <h2>Borrels</h2>
        {runs === undefined && !failed && <p className={styles.muted}>Laden…</p>}
        {failed && <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>}
        {runs !== undefined && (
          <RunList
            runs={runs}
            detailId={detailId}
            compareA={compareA}
            compareB={compareB}
            onDetail={setDetailId}
            onCompareA={setCompareA}
            onCompareB={setCompareB}
            onDelete={setDeleting}
          />
        )}
        {error !== null && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </section>
      {detail === undefined ? (
        <p className={styles.muted}>Kies een borrel voor details.</p>
      ) : (
        <section className={styles.section} aria-label={`Details van ${detail.name}`}>
          <h2>{detail.name}</h2>
          <RunDetail runId={detail.run_id} />
          <ExportPanel runId={detail.run_id} />
        </section>
      )}
      <section className={styles.section} aria-label="Vergelijk">
        <h2>Vergelijk</h2>
        <CompareView a={compareA} b={compareB} />
      </section>
      <ConfirmDialog
        open={deleting !== null}
        message={`'${deleting?.name ?? ''}' verwijderen? Alle verkopen en exports gaan verloren.`}
        confirmLabel="Verwijderen bevestigen"
        cancelLabel="Annuleren"
        confirmText={deleting?.name}
        onConfirm={() => deleting !== null && void remove(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  )
}

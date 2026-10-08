/**
 * The Borrel section (Phase 6 SD4; AC24, AC25, AC39; PD2): the current run's
 * name and status, and "Live zetten" for a draft, behind `ConfirmDialog`.
 * With no run, "Geen borrel" and a "Nieuwe borrel" form; a 409
 * `draft_exists` opens the draft that already exists.
 */
import { type FormEvent, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { HttpError, request } from '../../lib/http'
import styles from './settings.module.css'
import { CurrentRun, fetchCurrentRun, useCurrentRun } from './useCurrentRun'

const STATUS = { draft: 'Concept', live: 'Live', ended: 'Afgelopen' } as const

const REFUSALS: Readonly<Record<string, string>> = {
  live_run_exists: 'Er is al een live borrel.',
  run_not_draft: 'Deze borrel staat niet meer in concept.',
  run_not_ready: 'Voeg eerst een drankje toe.',
  run_not_found: 'Deze borrel bestaat niet meer.',
  forbidden: 'Geen toegang',
}

function failureText(error: unknown): string {
  if (error instanceof HttpError && error.status === 422) return 'Vul een naam in (1–100 tekens).'
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  return 'Verbindingsfout. Probeer opnieuw.'
}

export function BorrelSection() {
  const { run, setRun, failed } = useCurrentRun()
  const [name, setName] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    if (name.trim() === '') return
    setBusy(true)
    try {
      setRun(await request('POST', '/api/runs', { body: { name }, schema: CurrentRun }))
      setError(null)
    } catch (failure) {
      if (failure instanceof HttpError && failure.code === 'draft_exists') {
        setRun(await fetchCurrentRun().catch(() => null))
        setError(null)
      } else {
        setError(failureText(failure))
      }
    } finally {
      setBusy(false)
    }
  }

  async function goLive(runId: number) {
    setAsking(false)
    setBusy(true)
    try {
      setRun(await request('POST', `/api/runs/${runId}/go-live`, { schema: CurrentRun }))
      setError(null)
    } catch (failure) {
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {run === undefined && !failed && <p className={styles.muted}>Laden…</p>}
      {failed && <p className={styles.muted}>Verbindingsfout. Probeer opnieuw.</p>}
      {run === null && (
        <form className={styles.row} onSubmit={(event) => void create(event)}>
          <p>Geen borrel</p>
          <label className={styles.inline}>
            Naam
            <input
              className={styles.input}
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={busy}>
            Nieuwe borrel
          </Button>
        </form>
      )}
      {run != null && (
        <div className={styles.row}>
          <strong>{run.name}</strong>
          <span className={styles.badge}>{STATUS[run.status]}</span>
          {run.status === 'draft' && (
            <Button disabled={busy} onClick={() => setAsking(true)}>
              Live zetten
            </Button>
          )}
          <ConfirmDialog
            open={asking}
            message={`'${run.name}' live zetten?`}
            confirmLabel="Bevestigen"
            cancelLabel="Annuleren"
            onConfirm={() => void goLive(run.run_id)}
            onCancel={() => setAsking(false)}
          />
        </div>
      )}
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </>
  )
}

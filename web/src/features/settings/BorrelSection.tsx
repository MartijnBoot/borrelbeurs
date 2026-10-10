/**
 * The Borrel section (Phase 6 SD4; AC24, AC25, AC39; PD2): the current run's
 * name and status, and "Live zetten" for a draft, behind `ConfirmDialog`.
 * With no run, "Geen borrel" and a "Nieuwe borrel" form; a 409
 * `draft_exists` opens the draft that already exists.
 *
 * Phase 7 (SD2, SD4; AC2, AC9, AC32): a live run has "Borrel afsluiten",
 * behind `ConfirmDialog` with the run's name to type; after it the form shows
 * again. The form's "Kopieer drankjes uit" lists the past runs and sends the
 * choice as `copy_from_run_id`; if the list cannot be fetched, only the empty
 * option is offered and the form still works.
 */
import { type FormEvent, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Select } from '../../components/ui/Select'
import { HttpError, request } from '../../lib/http'
import { fetchPastRuns, type PastRun } from './pastRuns'
import styles from './settings.module.css'
import { CurrentRun, fetchCurrentRun, useCurrentRun } from './useCurrentRun'

const STATUS = { draft: 'Concept', live: 'Live', ended: 'Afgelopen' } as const

const REFUSALS: Readonly<Record<string, string>> = {
  live_run_exists: 'Er is al een live borrel.',
  run_not_draft: 'Deze borrel staat niet meer in concept.',
  run_not_ready: 'Voeg eerst een drankje toe.',
  run_not_found: 'Deze borrel bestaat niet meer.',
  name_mismatch: 'Naam komt niet overeen.',
  run_not_live: 'Deze borrel is niet live.',
  forbidden: 'Geen toegang',
}

/** The codes first: a 422 `name_mismatch` is not a bad name for a new borrel. */
function failureText(error: unknown): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  if (error instanceof HttpError && error.status === 422) return 'Vul een naam in (1–100 tekens).'
  return 'Verbindingsfout. Probeer opnieuw.'
}

export function BorrelSection() {
  const { run, setRun, failed } = useCurrentRun()
  const [name, setName] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [pastRuns, setPastRuns] = useState<PastRun[]>([])
  const [asking, setAsking] = useState<'live' | 'close' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const noRun = run === null
  useEffect(() => {
    if (!noRun) return
    let current = true
    fetchPastRuns().then(
      (runs) => current && setPastRuns(runs),
      () => current && setPastRuns([]),
    )
    return () => {
      current = false
    }
  }, [noRun])

  async function create(event: FormEvent) {
    event.preventDefault()
    if (name.trim() === '') return
    setBusy(true)
    const body = copyFrom === '' ? { name } : { name, copy_from_run_id: Number(copyFrom) }
    try {
      setRun(await request('POST', '/api/runs', { body, schema: CurrentRun }))
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

  async function act(path: string, body: object | undefined, next: (ran: CurrentRun) => void) {
    setAsking(null)
    setBusy(true)
    try {
      next(await request('POST', path, { body, schema: CurrentRun }))
      setError(null)
    } catch (failure) {
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  const copyOptions = [
    { value: '', label: '—' },
    ...pastRuns.map((past) => ({ value: String(past.run_id), label: past.name })),
  ]

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
          <Select
            label="Kopieer drankjes uit"
            value={copyFrom}
            options={copyOptions}
            onChange={setCopyFrom}
          />
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
            <Button disabled={busy} onClick={() => setAsking('live')}>
              Live zetten
            </Button>
          )}
          {run.status === 'live' && (
            <Button disabled={busy} onClick={() => setAsking('close')}>
              Borrel afsluiten
            </Button>
          )}
          <ConfirmDialog
            open={asking === 'live'}
            message={`'${run.name}' live zetten?`}
            confirmLabel="Bevestigen"
            cancelLabel="Annuleren"
            onConfirm={() => void act(`/api/runs/${run.run_id}/go-live`, undefined, setRun)}
            onCancel={() => setAsking(null)}
          />
          <ConfirmDialog
            open={asking === 'close'}
            message={`'${run.name}' afsluiten? De borrel stopt voor iedereen.`}
            confirmLabel="Afsluiten"
            cancelLabel="Annuleren"
            confirmText={run.name}
            onConfirm={() =>
              void act(`/api/runs/${run.run_id}/close`, { confirm_name: run.name }, () => {
                setCopyFrom('')
                setRun(null)
              })
            }
            onCancel={() => setAsking(null)}
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

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
 *
 * B-04 (SD4, SD13; AC7-AC10, AC22, AC23): a "Profiel" select beside it, "—" plus
 * every profile, sent as `profile_id` when one is picked, with no extra confirm.
 * If the profiles cannot be fetched only "—" is offered. A profile gone meanwhile
 * is said so and dropped; a stored value outside today's rules is named by its
 * setting name (`names`).
 */
import { type FormEvent, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Select } from '../../components/ui/Select'
import { HttpError, request } from '../../lib/http'
import { fetchPastRuns, type PastRun } from './pastRuns'
import styles from './settings.module.css'
import { CurrentRun, fetchCurrentRun, useCurrentRun } from './useCurrentRun'
import { bumpProfiles, useProfiles } from './useProfiles'
import { faultsOf } from './useRunConfig'

const STATUS = { draft: 'Concept', live: 'Live', ended: 'Afgelopen' } as const

const REFUSALS: Readonly<Record<string, string>> = {
  live_run_exists: 'Er is al een live borrel.',
  run_not_draft: 'Deze borrel staat niet meer in concept.',
  run_not_ready: 'Voeg eerst een drankje toe.',
  run_not_found: 'Deze borrel bestaat niet meer.',
  name_mismatch: 'Naam komt niet overeen.',
  run_not_live: 'Deze borrel is niet live.',
  profile_not_found: 'Dit profiel bestaat niet meer.',
  forbidden: 'Geen toegang',
}

/**
 * The codes first: a 422 `name_mismatch` is not a bad name for a new borrel. Then a
 * 422 naming a profile's setting (B-04 PD12), before the name fallback.
 */
function failureText(error: unknown, names: Readonly<Record<string, string>>): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  const field = Object.keys(faultsOf(error)).find((key) => names[key] !== undefined)
  if (field !== undefined)
    return `Profiel niet toegepast: '${names[field]}' valt buiten de toegestane waarden.`
  if (error instanceof HttpError && error.status === 422) return 'Vul een naam in (1–100 tekens).'
  return 'Verbindingsfout. Probeer opnieuw.'
}

export interface BorrelSectionProps {
  /** Wire name → the setting's name from the explanations (B-04 PD11). */
  names: Readonly<Record<string, string>>
}

export function BorrelSection({ names }: BorrelSectionProps) {
  const { run, setRun, failed } = useCurrentRun()
  const { profiles } = useProfiles()
  const [name, setName] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [picked, setPicked] = useState('')
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
    const body = {
      name,
      ...(copyFrom === '' ? {} : { copy_from_run_id: Number(copyFrom) }),
      ...(profile === '' ? {} : { profile_id: Number(profile) }),
    }
    try {
      setRun(await request('POST', '/api/runs', { body, schema: CurrentRun }))
      setError(null)
    } catch (failure) {
      if (failure instanceof HttpError && failure.code === 'draft_exists') {
        setRun(await fetchCurrentRun().catch(() => null))
        setError(null)
      } else {
        setError(failureText(failure, names))
        if (failure instanceof HttpError && failure.code === 'profile_not_found') bumpProfiles()
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
      setError(failureText(failure, names))
    } finally {
      setBusy(false)
    }
  }

  // A picked profile deleted since (a bump refetched the list) falls back to "—".
  const profile = profiles.some((p) => String(p.profile_id) === picked) ? picked : ''
  const profileOptions = [
    { value: '', label: '—' },
    ...profiles.map((p) => ({ value: String(p.profile_id), label: p.name })),
  ]

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
          <Select label="Profiel" value={profile} options={profileOptions} onChange={setPicked} />
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

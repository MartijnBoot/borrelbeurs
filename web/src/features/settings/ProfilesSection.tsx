/**
 * The Profielen section (B-04 SD2, SD5, SD6, SD10, SD12, SD14).
 *
 * The list: one row per profile, "<naam> · opgeslagen <d mmm HH:mm> · uit
 * '<borrelnaam>'", in the server's order, each with "Verwijderen" behind a plain
 * confirm; it shows with or without a run (AC21). No value of a profile is shown
 * (SD12). "Opslaan als profiel" saves the current draft or live run's 22 under a
 * name; a 409 `profile_exists` asks "overschrijven?" and on confirm resends with
 * `overwrite`. A 422 on a run value is named by its setting name (`names`, built
 * by the page from the explanations, AC23), never by its wire name.
 *
 * On a draft only, "Profiel laden" asks first (SD13) and then replaces the
 * draft's 22 with the profile's (`POST /api/runs/{id}/profile`). It reloads the
 * current run, which every settings section refetches its config from, so they
 * show the loaded values and a section with unsaved edits offers "Overnemen"
 * (AC16).
 *
 * B-07 (SD5; PD11): a load whose Prijsstap leaves a drink no room between its
 * bounds is a 422 `bounds_collision`; its message, which names the drink, is
 * shown as the server wrote it.
 */
import { type FormEvent, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Select } from '../../components/ui/Select'
import { HttpError, request } from '../../lib/http'
import { formatDayMonthTime } from '../../lib/time'
import styles from './settings.module.css'
import { useCurrentRun } from './useCurrentRun'
import { bumpProfiles, Profile, useProfiles } from './useProfiles'
import { faultsOf, Revision } from './useRunConfig'

const CONNECTION = 'Verbindingsfout. Probeer opnieuw.'
const GONE = 'Dit profiel bestaat niet meer.'

/** The setting a 422 names, by its name for a person; `null` when it names no setting. */
function settingOf(error: unknown, names: Readonly<Record<string, string>>): string | null {
  const field = Object.keys(faultsOf(error)).find((key) => names[key] !== undefined)
  return field === undefined ? null : names[field]
}

function loadFailure(error: unknown, names: Readonly<Record<string, string>>): string {
  if (error instanceof HttpError && error.code === 'bounds_collision')
    return Object.values(faultsOf(error))[0] ?? error.message
  const setting = settingOf(error, names)
  if (setting !== null)
    return `Profiel niet toegepast: '${setting}' valt buiten de toegestane waarden.`
  if (error instanceof HttpError && error.code === 'profile_not_found') return GONE
  if (error instanceof HttpError && error.code === 'run_not_draft')
    return 'Deze borrel is geen concept meer.'
  return CONNECTION
}

function saveFailure(error: unknown, names: Readonly<Record<string, string>>): string {
  const setting = settingOf(error, names)
  if (setting !== null) return `Niet opgeslagen: '${setting}' valt buiten de toegestane waarden.`
  // BorrelSection's text for the same code.
  if (error instanceof HttpError && error.code === 'run_not_found')
    return 'Deze borrel bestaat niet meer.'
  if (error instanceof HttpError && error.status === 422) return 'Vul een naam in (1–100 tekens).'
  return CONNECTION
}

export interface ProfilesSectionProps {
  /** Wire name → the setting's name from the explanations (B-01, B-03; PD11). */
  names: Readonly<Record<string, string>>
}

export function ProfilesSection({ names }: ProfilesSectionProps) {
  const { run, reload } = useCurrentRun()
  const { profiles, failed } = useProfiles()
  const [name, setName] = useState('')
  const [overwriting, setOverwriting] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Profile | null>(null)
  const [chosen, setChosen] = useState('')
  const [loading, setLoading] = useState<Profile | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSave = run != null && (run.status === 'draft' || run.status === 'live')
  const canLoad = run?.status === 'draft' && profiles.length > 0
  // The select's choice, or the first profile while none (or a deleted one) is chosen.
  const toLoad = profiles.find((p) => String(p.profile_id) === chosen) ?? profiles[0]

  async function save(overwrite: boolean) {
    if (run == null) return
    setOverwriting(null)
    setBusy(true)
    const body = overwrite ? { name, run_id: run.run_id, overwrite } : { name, run_id: run.run_id }
    try {
      await request('POST', '/api/profiles', { body, schema: Profile })
      setName('')
      setError(null)
      bumpProfiles()
    } catch (failure) {
      if (failure instanceof HttpError && failure.code === 'profile_exists') {
        const listed = profiles.find((p) => p.profile_id === failure.details.profile_id)
        setOverwriting(listed?.name ?? name.trim())
        setError(null)
      } else if (failure instanceof HttpError && failure.code === 'run_ended') {
        // The run ended meanwhile: reloading it takes the save form away.
        setError(null)
        await reload()
      } else {
        setError(saveFailure(failure, names))
        if (failure instanceof HttpError && failure.code === 'run_not_found') await reload()
      }
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (name.trim() === '') return
    void save(false)
  }

  async function load(profile: Profile) {
    if (run == null) return
    setLoading(null)
    setBusy(true)
    try {
      await request('POST', `/api/runs/${run.run_id}/profile`, {
        body: { profile_id: profile.profile_id },
        schema: Revision,
      })
      setError(null)
      await reload()
    } catch (failure) {
      setError(loadFailure(failure, names))
      if (failure instanceof HttpError && failure.code === 'profile_not_found') bumpProfiles()
      if (failure instanceof HttpError && failure.code === 'run_not_draft') await reload()
    } finally {
      setBusy(false)
    }
  }

  async function remove(profile: Profile) {
    setDeleting(null)
    setBusy(true)
    try {
      await request('DELETE', `/api/profiles/${profile.profile_id}`, { schema: z.unknown() })
      setError(null)
    } catch (failure) {
      setError(
        failure instanceof HttpError && failure.code === 'profile_not_found' ? GONE : CONNECTION,
      )
    } finally {
      bumpProfiles()
      setBusy(false)
    }
  }

  return (
    <>
      {failed && <p className={styles.muted}>{CONNECTION}</p>}
      {!failed && profiles.length === 0 && <p className={styles.muted}>Nog geen profielen</p>}
      {profiles.length > 0 && (
        <ul className={styles.subsection}>
          {profiles.map((profile) => (
            <li key={profile.profile_id} className={styles.row}>
              <span>
                {`${profile.name} · opgeslagen ${formatDayMonthTime(Date.parse(profile.saved_at))}`}
                {` · uit '${profile.source_run_name}'`}
              </span>
              <Button disabled={busy} onClick={() => setDeleting(profile)}>
                Verwijderen
              </Button>
            </li>
          ))}
        </ul>
      )}
      {canSave && (
        <form className={styles.row} onSubmit={submit}>
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
            Opslaan als profiel
          </Button>
        </form>
      )}
      {canLoad && toLoad !== undefined && (
        <div className={styles.row}>
          <Select
            label="Profiel laden"
            value={String(toLoad.profile_id)}
            options={profiles.map((p) => ({ value: String(p.profile_id), label: p.name }))}
            onChange={setChosen}
          />
          <Button disabled={busy} onClick={() => setLoading(toLoad)}>
            Laden
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={loading !== null}
        message={`Profiel '${loading?.name ?? ''}' laden op '${run?.name ?? ''}'? Dit vervangt de instellingen van deze borrel.`}
        confirmLabel="Laden"
        cancelLabel="Annuleren"
        onConfirm={() => loading !== null && void load(loading)}
        onCancel={() => setLoading(null)}
      />
      <ConfirmDialog
        open={overwriting !== null}
        message={`Profiel '${overwriting ?? ''}' overschrijven?`}
        confirmLabel="Overschrijven"
        cancelLabel="Annuleren"
        onConfirm={() => void save(true)}
        onCancel={() => setOverwriting(null)}
      />
      <ConfirmDialog
        open={deleting !== null}
        message={`Profiel '${deleting?.name ?? ''}' verwijderen?`}
        confirmLabel="Verwijderen"
        cancelLabel="Annuleren"
        onConfirm={() => deleting !== null && void remove(deleting)}
        onCancel={() => setDeleting(null)}
      />
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </>
  )
}

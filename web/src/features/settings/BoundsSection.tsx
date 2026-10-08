/**
 * 🔒 Min/Max/Startprijs (Phase 6 SD25; AC1, AC3, AC11): one row per active
 * drink, its three bounds as `MoneyField`s. Each row is its own
 * `useEditableRecord` and its own save, which sends one `PATCH` with only that
 * row's changed bounds -- or nothing, "Niets te wijzigen". `p_min < p0 < p_max`
 * is checked here first; the server's 422 shows under the field it names. On the
 * live run the server holds each affected quoted price (SD9).
 */
import { type FormEvent, useId, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { MoneyField } from '../../components/ui/MoneyField'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import styles from './settings.module.css'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

type Drink = RunConfig['drinks'][number]

interface Bounds {
  p_min_cents: number
  p0_cents: number
  p_max_cents: number
}

const FIELDS = [
  ['p_min_cents', 'Min'],
  ['p0_cents', 'Start'],
  ['p_max_cents', 'Max'],
] as const

export function BoundsSection() {
  const { config, failed, reload } = useRunConfig()
  if (config === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  return (
    <>
      {config.drinks
        .filter((drink) => drink.active)
        .map((drink) => (
          <BoundsRow key={drink.drink_id} runId={config.run.run_id} drink={drink} onDone={reload} />
        ))}
    </>
  )
}

function BoundsRow({
  runId,
  drink,
  onDone,
}: {
  runId: number
  drink: Drink
  onDone: () => Promise<void>
}) {
  const server = useMemo<Bounds>(
    () => ({
      p_min_cents: drink.p_min_cents,
      p0_cents: drink.p0_cents,
      p_max_cents: drink.p_max_cents,
    }),
    [drink.p_min_cents, drink.p0_cents, drink.p_max_cents],
  )
  const record = useEditableRecord(server)
  const [faults, setFaults] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const titleId = useId()
  const values = record.values

  async function save(event: FormEvent) {
    event.preventDefault()
    setFaults({})
    if (values !== null) {
      const [low, mid, high] = [values.p_min_cents, values.p0_cents, values.p_max_cents]
      const ordered =
        typeof low === 'number' &&
        typeof mid === 'number' &&
        typeof high === 'number' &&
        low < mid &&
        mid < high
      if (!ordered && record.dirty) {
        setError('Min < Start < Max')
        return
      }
    }
    setBusy(true)
    try {
      const result = await record.save(async (patch) => {
        await request('PATCH', `/api/runs/${runId}/drinks/${drink.drink_id}`, {
          body: patch,
          schema: Revision,
        })
        await onDone()
      })
      if (result === 'nothing') setNotice('Niets te wijzigen')
      setError(result === 'invalid' ? 'Vul alle drie de prijzen in.' : null)
    } catch (failure) {
      const byField = faultsOf(failure)
      setFaults(byField)
      setError(Object.keys(byField).length === 0 ? 'Opslaan mislukt. Probeer opnieuw.' : null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      role="group"
      aria-labelledby={titleId}
      className={styles.subsection}
      onSubmit={(event) => void save(event)}
    >
      <h3 id={titleId}>{drink.name}</h3>
      {record.conflict && (
        <p className={styles.row}>
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.row}>
        {FIELDS.map(([field, label]) => (
          <MoneyField
            key={field}
            label={label}
            cents={values?.[field] ?? null}
            onChange={(value) => record.set(field, value)}
            error={faults[field]}
          />
        ))}
        <Button type="submit" disabled={busy}>
          Opslaan
        </Button>
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

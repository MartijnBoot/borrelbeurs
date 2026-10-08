/**
 * ⏳ Idle (Phase 6 SD11, SD20; AC1, AC2, AC5, AC7, AC22): admin only (D-44).
 *
 * v1's decay/rise minutes and strengths as `NumberField`s, and a checkbox per
 * active drink for each target list, held as `drink_id`s. The form edits a
 * `useEditableRecord` copy of the live run's params (`GET config`, refetched
 * on every `config` message), and "💾 Opslaan idle" sends only what changed as
 * `PATCH config {params}` -- nothing at all when clean. A removed drink has no
 * checkbox, since the list is the store's active drinks.
 */
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { NumberField } from '../../components/ui/NumberField'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import { selectActiveDrinks, useExchange } from '../exchange'
import styles from './ManipulationPage.module.css'

const IdleParams = z.object({
  idle_decay_minutes: z.number(),
  idle_rise_minutes: z.number(),
  idle_strength: z.number(),
  idle_rise_strength: z.number(),
  idle_targets: z.array(z.number().int()),
  idle_rise_targets: z.array(z.number().int()),
})
type IdleParams = z.infer<typeof IdleParams>

const Config = z.object({ params: IdleParams })

const NUMBERS = [
  ['idle_decay_minutes', '🕒 Idle-decay (min)'],
  ['idle_strength', '⬇️ Decay-sterkte'],
  ['idle_rise_minutes', '🕒 Idle-rise (min)'],
  ['idle_rise_strength', '⬆️ Rise-sterkte'],
] as const

const TARGETS = [
  ['idle_targets', 'Decay targets'],
  ['idle_rise_targets', 'Rise targets'],
] as const

/** The live run's idle params; refetched when a `config` message changes the store's. */
function useIdleParams() {
  const runId = useExchange((s) => s.run?.run_id ?? null)
  const storeParams = useExchange((s) => s.params)
  const [params, setParams] = useState<IdleParams | null>(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(
    (id: number) =>
      request('GET', `/api/runs/${id}/config`, { schema: Config }).then(
        (config) => {
          setParams(config.params)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    if (runId !== null) void load(runId)
  }, [load, runId, storeParams])

  const reload = useCallback(async () => {
    if (runId !== null) await load(runId)
  }, [load, runId])

  return { params, failed, reload }
}

export function IdleSection() {
  const runId = useExchange((s) => s.run?.run_id ?? null)
  const drinks = useExchange(selectActiveDrinks)
  const { params, failed, reload } = useIdleParams()
  const record = useEditableRecord(params)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (runId === null || record.values === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const values = record.values

  function toggle(list: (typeof TARGETS)[number][0], drinkId: number) {
    const current = values[list]
    const ids = Array.isArray(current) ? current : []
    record.set(list, ids.includes(drinkId) ? ids.filter((id) => id !== drinkId) : [...ids, drinkId])
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result = await record.save(async (patch) => {
        await request('PATCH', `/api/runs/${runId}/config`, {
          body: { params: patch },
          schema: z.unknown(),
        })
        await reload()
      })
      if (result === 'nothing') setNotice('Niets te wijzigen')
      if (result === 'sent') setNotice('Opgeslagen')
    } catch {
      setError('Opslaan mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.row}>
        {NUMBERS.map(([field, label]) => (
          <NumberField
            key={field}
            label={label}
            value={values[field]}
            onChange={(value) => record.set(field, value)}
            error={
              values[field] === null
                ? 'Verplicht'
                : values[field] === 'invalid'
                  ? 'Ongeldig getal'
                  : undefined
            }
          />
        ))}
      </div>
      {TARGETS.map(([list, label]) => (
        <fieldset key={list} className={styles.targets} aria-label={label}>
          <legend>{label}</legend>
          {drinks.map((drink) => {
            const ids = values[list]
            return (
              <label key={drink.drink_id} className={styles.check}>
                <input
                  type="checkbox"
                  checked={Array.isArray(ids) && ids.includes(drink.drink_id)}
                  onChange={() => toggle(list, drink.drink_id)}
                />
                {drink.name}
              </label>
            )
          })}
        </fieldset>
      ))}
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          💾 Opslaan idle
        </Button>
        {error !== null && <span className={styles.error}>{error}</span>}
      </div>
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

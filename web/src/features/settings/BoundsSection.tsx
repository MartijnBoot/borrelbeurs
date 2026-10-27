/**
 * Min/Max/Startprijs (Phase 6 SD25; AC1, AC3, AC11): one row per active
 * drink, its three bounds as `MoneyField`s under B-01's names, each with an (i)
 * (E17-E19). Each row is its own
 * `useEditableRecord` and its own save, which sends one `PATCH` with only that
 * row's changed bounds -- or nothing, "Niets te wijzigen". `p_min < p0 < p_max`
 * is checked here first; the server's 422 shows under the field it names. On the
 * live run the server holds each affected quoted price (SD9).
 *
 * B-07 (SD1, SD6, SD10; PD9): a Minimumprijs or Maximumprijs the save would send
 * must be a multiple of the Prijsstap, else SD1's message shows under it and
 * nothing is sent. A stored bound off the grid shows "Niet op de Prijsstap: kies
 * x of y." while it is untouched; it is never sent, so the row still saves.
 */
import { type FormEvent, useId, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { MoneyField } from '../../components/ui/MoneyField'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import styles from './settings.module.css'
import { gridMessage, offGridHint, onGrid, stepCents } from './grid'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

type Drink = RunConfig['drinks'][number]

interface Bounds {
  p_min_cents: number
  p0_cents: number
  p_max_cents: number
}

const FIELDS = ['p_min_cents', 'p0_cents', 'p_max_cents'] as const
const GRID = ['p_min_cents', 'p_max_cents'] as const

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
          <BoundsRow
            key={drink.drink_id}
            runId={config.run.run_id}
            drink={drink}
            step={stepCents(config.params.step_quant)}
            onDone={reload}
          />
        ))}
    </>
  )
}

function BoundsRow({
  runId,
  drink,
  step,
  onDone,
}: {
  runId: number
  drink: Drink
  step: number
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
        setError('Minimumprijs < Startprijs < Maximumprijs')
        return
      }
      const offGrid: Record<string, string> = {}
      for (const field of GRID) {
        const sent = record.patch[field]
        if (typeof sent === 'number' && !onGrid(sent, step)) {
          offGrid[field] = gridMessage(sent, step)
        }
      }
      if (Object.keys(offGrid).length > 0) {
        setFaults(offGrid)
        setError(null)
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
        {FIELDS.map((field) => (
          <MoneyField
            key={field}
            label={explanations[field].name}
            info={explanations[field]}
            cents={values?.[field] ?? null}
            onChange={(value) => record.set(field, value)}
            hint={
              field !== 'p0_cents' &&
              values?.[field] === drink[field] &&
              !onGrid(drink[field], step)
                ? offGridHint(drink[field], step)
                : undefined
            }
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

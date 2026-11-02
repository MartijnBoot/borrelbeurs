/**
 * Prijsstap, at the top of Spelopzet's Prijzen (B-12 SD4, PD9), above the
 * bounds it constrains. Its own form: a `useEditableRecord` copy of the run's
 * `step_quant`, saved as `PATCH config {params: {step_quant}}` by "Opslaan
 * prijsstap", nothing at all when clean ("Niets te wijzigen"). An empty or
 * unparseable step blocks the save; a server change while editing keeps the
 * input and offers "Overnemen".
 *
 * B-07 (SD3; PD10): a new Prijsstap moves every active drink's off-grid bound
 * inward. When the save holds a valid new step and at least one bound would move
 * (from this form's own config), a `ConfirmDialog` lists the moves first:
 * "Annuleren" sends nothing and keeps the input, "Opslaan" sends. With no move,
 * it sends as before. The server recomputes the moves and is what is stored; a
 * drink left with no room comes back as its `bounds_collision` message under
 * Prijsstap.
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { NumberField } from '../../components/ui/NumberField'
import { Toast } from '../../components/ui/Toast'
import { centsText } from '../../lib/format'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import { type BoundMove, boundMoves, stepCents } from './grid'
import styles from './settings.module.css'
import { faultsOf, Revision, useRunConfig } from './useRunConfig'

const BOUND_NAMES: Readonly<Record<BoundMove['field'], string>> = {
  p_min_cents: 'Minimumprijs',
  p_max_cents: 'Maximumprijs',
}

/** A step the server would accept: above 0, at most 5, in whole cents. */
function validStep(step: unknown): step is number {
  return (
    typeof step === 'number' &&
    step > 0 &&
    step <= 5 &&
    Math.abs(step * 100 - Math.round(step * 100)) < 1e-9
  )
}

export function PriceStepSection() {
  const { config, failed, reload } = useRunConfig()
  const server = useMemo(
    () => (config === null ? null : { step_quant: config.params.step_quant }),
    [config],
  )
  const record = useEditableRecord(server)
  const [notice, setNotice] = useState<string | null>(null)
  const [fault, setFault] = useState<string | undefined>(undefined)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [moving, setMoving] = useState<{ step: number; moves: BoundMove[] } | null>(null)

  if (config === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const runId = config.run.run_id
  const drinks = config.drinks

  function submit(event: FormEvent) {
    event.preventDefault()
    const step = record.patch.step_quant
    if (validStep(step)) {
      const moves = boundMoves(drinks, stepCents(step))
      if (moves.length > 0) {
        setMoving({ step, moves })
        return
      }
    }
    void send()
  }

  async function send() {
    setMoving(null)
    setFault(undefined)
    setSaveError(null)
    setBusy(true)
    try {
      const result = await record.save(async (patch) => {
        await request('PATCH', `/api/runs/${runId}/config`, {
          body: { params: patch },
          schema: Revision,
        })
        await reload()
      })
      if (result === 'nothing') setNotice('Niets te wijzigen')
      if (result === 'sent') setNotice('Opgeslagen')
    } catch (failure) {
      const byField = faultsOf(failure)
      setFault(byField.step_quant)
      if (byField.step_quant === undefined) setSaveError('Opslaan mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  const value = record.values?.step_quant ?? null
  return (
    <form onSubmit={submit}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.grid}>
        <NumberField
          label={explanations.step_quant.name}
          info={explanations.step_quant}
          value={value}
          onChange={(next) => record.set('step_quant', next)}
          error={value === null ? 'Verplicht' : value === 'invalid' ? 'Ongeldig getal' : fault}
        />
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          Opslaan prijsstap
        </Button>
        {saveError !== null && <span className={styles.error}>{saveError}</span>}
      </div>
      <Toast message={notice} onDone={() => setNotice(null)} />
      <ConfirmDialog
        open={moving !== null}
        message={
          moving !== null && (
            <>
              <p>
                Prijsstap {centsText(stepCents(moving.step))} opslaan? Deze grenzen schuiven mee:
              </p>
              <ul>
                {moving.moves.map((move) => (
                  <li key={`${move.name}-${move.field}`}>
                    {move.name}: {BOUND_NAMES[move.field]} {centsText(move.from)} →{' '}
                    {centsText(move.to)}
                  </li>
                ))}
              </ul>
            </>
          )
        }
        confirmLabel="Opslaan"
        cancelLabel="Annuleren"
        onConfirm={() => void send()}
        onCancel={() => setMoving(null)}
      />
    </form>
  )
}

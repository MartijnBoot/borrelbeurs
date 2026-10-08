/**
 * ⚙️ Globale instellingen (Phase 6 SD8, SD25, SD27; AC1, AC2, AC3, AC5, AC28):
 * v1's global params and the candle interval, each a `NumberField` under v1's
 * label (`settings.html`, "sec-params").
 *
 * The form edits a `useEditableRecord` copy of the run's config. Saving sends
 * only the changed fields -- params under `params`, the candle interval at the
 * top level -- and nothing at all when clean ("Niets te wijzigen", AC2). An
 * empty or unparseable field blocks the save (AC3). A server change while
 * editing keeps the input and offers "Overnemen" (AC5). A 422 shows under the
 * field it names.
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { NumberField } from '../../components/ui/NumberField'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import styles from './settings.module.css'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

const FIELDS = [
  ['step_quant', '🧱 Tickgrootte'],
  ['eta', '⚡ Snelheid'],
  ['K', '🎚️ Drempel'],
  ['lambda_orders', '⚔️ Rivaliteit'],
  ['alpha_price', '🧭 Aantrekking naar gemiddelde'],
  ['phi_persist', '📈 Na-ijlen'],
  ['decay_rho', '🧠 Geheugen (ρ)'],
  ['history_window_minutes', '🗂️ Historie (min)'],
  ['refresh_minutes', '🔁 Update-interval (min)'],
  ['candle_interval_s', '🕯️ Kaarseninterval (sec)'],
] as const

type Field = (typeof FIELDS)[number][0]
type GlobalRecord = Record<Field, number>

function recordOf(config: RunConfig): GlobalRecord {
  const { params, run } = config
  return {
    step_quant: params.step_quant,
    eta: params.eta,
    K: params.K,
    lambda_orders: params.lambda_orders,
    alpha_price: params.alpha_price,
    phi_persist: params.phi_persist,
    decay_rho: params.decay_rho,
    history_window_minutes: params.history_window_minutes,
    refresh_minutes: params.refresh_minutes,
    candle_interval_s: run.candle_interval_s,
  }
}

export function GlobalSection() {
  const { config, failed, reload } = useRunConfig()
  const server = useMemo(() => (config === null ? null : recordOf(config)), [config])
  const record = useEditableRecord(server)
  const [notice, setNotice] = useState<string | null>(null)
  const [faults, setFaults] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (config === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const runId = config.run.run_id

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFaults({})
    setSaveError(null)
    setBusy(true)
    try {
      const result = await record.save(async (patch) => {
        const { candle_interval_s, ...params } = patch
        const body = {
          ...(Object.keys(params).length > 0 ? { params } : {}),
          ...(candle_interval_s !== undefined ? { candle_interval_s } : {}),
        }
        await request('PATCH', `/api/runs/${runId}/config`, { body, schema: Revision })
        await reload()
      })
      if (result === 'nothing') setNotice('Niets te wijzigen')
      if (result === 'sent') setNotice('Opgeslagen')
    } catch (failure) {
      const byField = faultsOf(failure)
      setFaults(byField)
      if (Object.keys(byField).length === 0) setSaveError('Opslaan mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  function errorFor(field: Field): string | undefined {
    const value = record.values?.[field]
    if (value === null) return 'Verplicht'
    if (value === 'invalid') return 'Ongeldig getal'
    return faults[field]
  }

  return (
    <form onSubmit={(event) => void submit(event)}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.grid}>
        {FIELDS.map(([field, label]) => (
          <NumberField
            key={field}
            label={label}
            value={record.values?.[field] ?? null}
            onChange={(value) => record.set(field, value)}
            error={errorFor(field)}
          />
        ))}
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          💾 Opslaan instellingen
        </Button>
        {saveError !== null && <span className={styles.error}>{saveError}</span>}
      </div>
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

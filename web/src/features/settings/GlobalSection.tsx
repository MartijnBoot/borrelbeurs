/**
 * Globale instellingen (Phase 6 SD8, SD25, SD27; AC1, AC2, AC3, AC5, AC28):
 * v1's global params and the candle interval, each a `NumberField` under its
 * B-01 name, with an (i) carrying its explanation (`explanations.json`, E1-E10).
 *
 * The form edits a `useEditableRecord` copy of the run's config. Saving sends
 * only the changed fields -- params under `params`, the candle interval at the
 * top level -- and nothing at all when clean ("Niets te wijzigen", AC2). An
 * empty or unparseable field blocks the save (AC3). A server change while
 * editing keeps the input and offers "Overnemen" (AC5). A 422 shows under the
 * field it names.
 *
 * B-03 (SD4-SD6) adds the noise after Kaarsbreedte, behind the same save:
 * Willekeurige ruis as a `Switch`, then its five settings as `NumberField`s
 * (E34-E39). Switching the noise off disables none of them (SD5).
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { NumberField } from '../../components/ui/NumberField'
import { Switch } from '../../components/ui/Switch'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import styles from './settings.module.css'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

const FIELDS = [
  'step_quant',
  'eta',
  'K',
  'lambda_orders',
  'alpha_price',
  'phi_persist',
  'decay_rho',
  'history_window_minutes',
  'refresh_minutes',
  'candle_interval_s',
] as const

/** After the Willekeurige ruis switch, in B-03 SD4's order. */
const NOISE_FIELDS = ['bm_sigma_y', 'bm_dt_minutes', 'flow_vol_amp', 'flow_beta', 'y_clip'] as const

type Field = (typeof FIELDS)[number] | (typeof NOISE_FIELDS)[number]
type GlobalRecord = Record<Field, number> & { bm_enabled: boolean }

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
    bm_enabled: params.bm_enabled,
    bm_sigma_y: params.bm_sigma_y,
    bm_dt_minutes: params.bm_dt_minutes,
    flow_vol_amp: params.flow_vol_amp,
    flow_beta: params.flow_beta,
    y_clip: params.y_clip,
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

  const numberField = (field: Field) => (
    <NumberField
      key={field}
      label={explanations[field].name}
      info={explanations[field]}
      value={record.values?.[field] ?? null}
      onChange={(value) => record.set(field, value)}
      error={errorFor(field)}
    />
  )

  return (
    <form onSubmit={(event) => void submit(event)}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.grid}>
        {FIELDS.map(numberField)}
        <div>
          <Switch
            label={explanations.bm_enabled.name}
            info={explanations.bm_enabled}
            checked={record.values?.bm_enabled === true}
            onChange={(on) => record.set('bm_enabled', on)}
          />
          {faults.bm_enabled !== undefined && (
            <span className={styles.error}>{faults.bm_enabled}</span>
          )}
        </div>
        {NOISE_FIELDS.map(numberField)}
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          Opslaan instellingen
        </Button>
        {saveError !== null && <span className={styles.error}>{saveError}</span>}
      </div>
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

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
 * B-03 (SD4-SD6) adds the noise, behind the same save: Willekeurige ruis as a
 * `Switch`, then its five settings as `NumberField`s (E34-E39).
 *
 * B-12 SD5, SD6 (PD11, PD12): one form and one "Opslaan instellingen", in three
 * groups with their own heading: "Hoe bestellingen de prijs bewegen",
 * "Willekeurige ruis" and "Koersbord". The five noise fields show only while
 * the switch is on. Turning it off discards nothing: a hidden field keeps its
 * edit, and the next save sends it. A hidden field that is empty or invalid
 * blocks the save, and a line per field names it and says to switch the noise
 * on to fix it. This amends B-03 SD5 ("disables none of them").
 *
 * B-12 SD3, SD4: Prijsstap, and B-07's confirm with it, is on Spelopzet's
 * Prijzen (`PriceStepSection`), and B-06's "Wallet verplicht" and "Rood staan
 * tot" are Betalen on Mensen en wallets (`PaymentSection`).
 */
import { type FormEvent, type ReactNode, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { NumberField } from '../../components/ui/NumberField'
import { Switch } from '../../components/ui/Switch'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import styles from './settings.module.css'
import groupStyles from './GlobalSection.module.css'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

/** PD11: what moves the price on an order, in SD5's order. */
const PRICE_FIELDS = [
  'eta',
  'K',
  'lambda_orders',
  'alpha_price',
  'phi_persist',
  'decay_rho',
  'refresh_minutes',
] as const

/** After the Willekeurige ruis switch, in B-03 SD4's order. */
const NOISE_FIELDS = ['bm_sigma_y', 'bm_dt_minutes', 'flow_vol_amp', 'flow_beta', 'y_clip'] as const

const BOARD_FIELDS = ['history_window_minutes', 'candle_interval_s'] as const

type Field =
  (typeof PRICE_FIELDS)[number] | (typeof NOISE_FIELDS)[number] | (typeof BOARD_FIELDS)[number]
type GlobalRecord = Record<Field, number> & { bm_enabled: boolean }

function recordOf(config: RunConfig): GlobalRecord {
  const { params, run } = config
  return {
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
  // PD12: hidden noise fields that blocked the last save.
  const [hiddenFaults, setHiddenFaults] = useState<readonly Field[]>([])

  if (config === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const runId = config.run.run_id
  const noiseOn = record.values?.bm_enabled === true

  function submit(event: FormEvent) {
    event.preventDefault()
    const values = record.values
    const blocked = noiseOn
      ? []
      : NOISE_FIELDS.filter((field) => values?.[field] === null || values?.[field] === 'invalid')
    setHiddenFaults(blocked)
    if (blocked.length === 0) void send()
  }

  async function send() {
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
    <form onSubmit={submit}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <Group title="Hoe bestellingen de prijs bewegen">{PRICE_FIELDS.map(numberField)}</Group>
      <Group title="Willekeurige ruis">
        <div>
          <Switch
            label={explanations.bm_enabled.name}
            info={explanations.bm_enabled}
            checked={noiseOn}
            onChange={(on) => record.set('bm_enabled', on)}
          />
          {faults.bm_enabled !== undefined && (
            <span className={styles.error}>{faults.bm_enabled}</span>
          )}
        </div>
        {noiseOn && NOISE_FIELDS.map(numberField)}
      </Group>
      {!noiseOn &&
        hiddenFaults.map((field) => (
          <p key={field} className={styles.error} role="alert">
            {explanations[field].name} is leeg of ongeldig. Zet Willekeurige ruis aan om het te
            verbeteren.
          </p>
        ))}
      <Group title="Koersbord">{BOARD_FIELDS.map(numberField)}</Group>
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

/** One of PD11's groups: a labelled region with its heading, its fields in the grid. */
function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={groupStyles.group} aria-label={title}>
      <h3>{title}</h3>
      <div className={styles.grid}>{children}</div>
    </section>
  )
}

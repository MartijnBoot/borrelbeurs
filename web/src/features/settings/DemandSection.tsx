/**
 * Vraag/Aanbod (Phase 6 SD25, SD27; AC1, AC2, AC3, AC5) -- the D-03 gate.
 *
 * v1 sent every coefficient of every drink on each save, and an emptied field
 * went out as 0 (D-03). Here:
 *
 * - **The switches** (`demand_enabled`, `auto_calibrate_s0`) are one
 *   `useEditableRecord`, saved as `PATCH config {params}` with only the one that
 *   changed.
 * - **The `a/d/s0/c` table** (headed by B-01's names, each with an (i);
 *   a cell is named "{drink} {name}") is one `useEditableRecord` over every active
 *   drink's four coefficients, keyed `"<drink_id>:<field>"`. Saving splits the
 *   patch by drink and sends one `PATCH` per changed drink, carrying only its
 *   changed coefficients. Untouched, it sends nothing: "Niets te wijzigen".
 *
 * The table scrolls sideways in its own box, so a phone's page never does (B-01 AC6).
 * An empty or unparseable cell blocks the save (AC3). A server change while
 * editing keeps the input and offers "Overnemen" (AC5).
 *
 * B-12 SD3, SD16, PD13: the two are separate sections on separate screens.
 * `DemandSwitches` (Beheer) stacks the two switches in one column.
 * `DemandTable` (Spelopzet) shows the table only while "Verwachte verkoop
 * meetellen" is on, and otherwise one sentence, with no link: an organiser
 * cannot open Beheer. It follows the switch live through `useRunConfig`, which
 * refetches on a `config` message. The table's record lives only while it
 * shows, so turning the switch off drops its unsaved edits, and the leave guard
 * stops counting them.
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { InfoButton } from '../../components/ui/InfoButton'
import { NumberField } from '../../components/ui/NumberField'
import { Switch } from '../../components/ui/Switch'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { type SaveResult, useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import styles from './settings.module.css'
import { Revision, type RunConfig, useRunConfig } from './useRunConfig'

const COEFFICIENTS = ['a', 'd', 's0', 'c'] as const
type Coefficient = (typeof COEFFICIENTS)[number]

const cell = (drinkId: number, field: Coefficient) => `${drinkId}:${field}`

function coefficientsOf(config: RunConfig): Record<string, number> {
  const record: Record<string, number> = {}
  for (const drink of config.drinks.filter((d) => d.active)) {
    for (const field of COEFFICIENTS) record[cell(drink.drink_id, field)] = drink[field]
  }
  return record
}

/** `{"12:a": 7.5, "12:c": 0.3}` as `{12: {a: 7.5, c: 0.3}}`. */
function byDrink(patch: Partial<Record<string, number>>): Map<number, Record<string, number>> {
  const drinks = new Map<number, Record<string, number>>()
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue
    const [id, field] = key.split(':')
    const drinkId = Number(id)
    drinks.set(drinkId, { ...drinks.get(drinkId), [field]: value })
  }
  return drinks
}

/** A save's outcome, as both forms show it: "Niets te wijzigen", or why it did not go. */
function useSaving() {
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(save: () => Promise<SaveResult>) {
    setBusy(true)
    try {
      const result = await save()
      if (result === 'nothing') setNotice('Niets te wijzigen')
      setError(result === 'invalid' ? 'Vul elk veld in met een geldig getal.' : null)
    } catch {
      setError('Opslaan mislukt. Probeer opnieuw.')
    } finally {
      setBusy(false)
    }
  }

  const outcome = (
    <>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <Toast message={notice} onDone={() => setNotice(null)} />
    </>
  )
  return { busy, run, outcome }
}

function Conflict({ onTake }: { onTake: () => void }) {
  return (
    <p className={styles.row}>
      Serverwaarden gewijzigd — overnemen?
      <Button onClick={onTake}>Overnemen</Button>
    </p>
  )
}

const loading = (failed: boolean) => (
  <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
)

/** Beheer's half (PD13): the two switches, one column, saved as `PATCH config {params}`. */
export function DemandSwitches() {
  const { config, failed, reload } = useRunConfig()
  const server = useMemo(
    () =>
      config === null
        ? null
        : {
            demand_enabled: config.params.demand_enabled,
            auto_calibrate_s0: config.params.auto_calibrate_s0,
          },
    [config],
  )
  const switches = useEditableRecord(server)
  const { busy, run, outcome } = useSaving()

  if (config === null || switches.values === null) return loading(failed)
  const runId = config.run.run_id
  const toggles = switches.values

  function save(event: FormEvent) {
    event.preventDefault()
    void run(() =>
      switches.save(async (patch) => {
        await request('PATCH', `/api/runs/${runId}/config`, {
          body: { params: patch },
          schema: Revision,
        })
        await reload()
      }),
    )
  }

  return (
    <>
      {switches.conflict && <Conflict onTake={switches.takeServer} />}
      <form className={styles.subsection} onSubmit={save}>
        <div className={styles.column}>
          <Switch
            label={explanations.demand_enabled.name}
            info={explanations.demand_enabled}
            checked={toggles.demand_enabled === true}
            onChange={(on) => switches.set('demand_enabled', on)}
          />
          <Switch
            label={explanations.auto_calibrate_s0.name}
            info={explanations.auto_calibrate_s0}
            checked={toggles.auto_calibrate_s0 === true}
            onChange={(on) => switches.set('auto_calibrate_s0', on)}
          />
        </div>
        <div className={styles.row}>
          <Button type="submit" disabled={busy}>
            Opslaan schakelaars
          </Button>
        </div>
      </form>
      {outcome}
    </>
  )
}

/** Spelopzet's half (PD13): the table while the switch is on, else one sentence. */
export function DemandTable() {
  const { config, failed, reload } = useRunConfig()
  if (config === null) return loading(failed)
  if (!config.params.demand_enabled) {
    return <p className={styles.muted}>Vraag/Aanbod staat uit. Zet het aan onder Beheer.</p>
  }
  return <CoefficientsForm config={config} reload={reload} />
}

function CoefficientsForm({ config, reload }: { config: RunConfig; reload: () => Promise<void> }) {
  const server = useMemo(() => coefficientsOf(config), [config])
  const table = useEditableRecord(server)
  const { busy, run, outcome } = useSaving()

  if (table.values === null) return null
  const runId = config.run.run_id
  const cells = table.values

  function save(event: FormEvent) {
    event.preventDefault()
    void run(() =>
      table.save(async (patch) => {
        for (const [drinkId, body] of byDrink(patch)) {
          await request('PATCH', `/api/runs/${runId}/drinks/${drinkId}`, {
            body,
            schema: Revision,
          })
        }
        await reload()
      }),
    )
  }

  return (
    <>
      {table.conflict && <Conflict onTake={table.takeServer} />}
      <form className={styles.subsection} onSubmit={save}>
        <div className={styles.tableScroll}>
          <table aria-label="Coëfficiënten" className={styles.table}>
            <thead>
              <tr>
                <th>Drankje</th>
                {COEFFICIENTS.map((field) => (
                  <th key={field}>
                    <span className={styles.columnHeader}>
                      <span>{explanations[field].name}</span>
                      <InfoButton explanation={explanations[field]} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {config.drinks
                .filter((drink) => drink.active)
                .map((drink) => (
                  <tr key={drink.drink_id}>
                    <th scope="row">{drink.name}</th>
                    {COEFFICIENTS.map((field) => {
                      const key = cell(drink.drink_id, field)
                      const value = cells[key] ?? null
                      return (
                        <td key={field}>
                          <NumberField
                            label={`${drink.name} ${explanations[field].name}`}
                            hideLabel
                            value={value}
                            onChange={(next) => table.set(key, next)}
                            error={
                              value === null
                                ? 'Verplicht'
                                : value === 'invalid'
                                  ? 'Ongeldig getal'
                                  : undefined
                            }
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <div className={styles.row}>
          <Button type="submit" disabled={busy}>
            Opslaan coëfficiënten
          </Button>
        </div>
      </form>
      {outcome}
    </>
  )
}

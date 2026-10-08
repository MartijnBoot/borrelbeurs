/**
 * 📈 Vraag/Aanbod (Phase 6 SD25, SD27; AC1, AC2, AC3, AC5) -- the D-03 gate.
 *
 * v1 sent every coefficient of every drink on each save, and an emptied field
 * went out as 0 (D-03). Here:
 *
 * - **The switches** (`demand_enabled`, `auto_calibrate_s0`) are one
 *   `useEditableRecord`, saved as `PATCH config {params}` with only the one that
 *   changed.
 * - **The `a/d/s0/c` table** is one `useEditableRecord` over every active
 *   drink's four coefficients, keyed `"<drink_id>:<field>"`. Saving splits the
 *   patch by drink and sends one `PATCH` per changed drink, carrying only its
 *   changed coefficients. Untouched, it sends nothing: "Niets te wijzigen".
 *
 * An empty or unparseable cell blocks the save (AC3). A server change while
 * editing keeps the input and offers "Overnemen" (AC5).
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { NumberField } from '../../components/ui/NumberField'
import { Switch } from '../../components/ui/Switch'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
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

export function DemandSection() {
  const { config, failed, reload } = useRunConfig()
  const switchesServer = useMemo(
    () =>
      config === null
        ? null
        : {
            demand_enabled: config.params.demand_enabled,
            auto_calibrate_s0: config.params.auto_calibrate_s0,
          },
    [config],
  )
  const tableServer = useMemo(() => (config === null ? null : coefficientsOf(config)), [config])
  const switches = useEditableRecord(switchesServer)
  const table = useEditableRecord(tableServer)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (config === null || switches.values === null || table.values === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const runId = config.run.run_id
  const toggles = switches.values
  const cells = table.values

  async function run(save: () => Promise<'sent' | 'nothing' | 'invalid'>) {
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

  function saveSwitches(event: FormEvent) {
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

  function saveTable(event: FormEvent) {
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

  const conflict = switches.conflict || table.conflict

  return (
    <>
      {conflict && (
        <p className={styles.row}>
          Serverwaarden gewijzigd — overnemen?
          <Button
            onClick={() => {
              switches.takeServer()
              table.takeServer()
            }}
          >
            Overnemen
          </Button>
        </p>
      )}
      <form className={styles.subsection} onSubmit={saveSwitches}>
        <div className={styles.row}>
          <Switch
            label="Vraag/aanbod actief"
            checked={toggles.demand_enabled === true}
            onChange={(on) => switches.set('demand_enabled', on)}
          />
          <Switch
            label="Evenwicht, s0, auto-kalibreren bij init/reset"
            checked={toggles.auto_calibrate_s0 === true}
            onChange={(on) => switches.set('auto_calibrate_s0', on)}
          />
          <Button type="submit" disabled={busy}>
            💾 Opslaan schakelaars
          </Button>
        </div>
      </form>
      <form className={styles.subsection} onSubmit={saveTable}>
        <table aria-label="Coëfficiënten" className={styles.table}>
          <thead>
            <tr>
              <th>Drankje</th>
              {COEFFICIENTS.map((field) => (
                <th key={field}>{field}</th>
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
                          label={`${drink.name} ${field}`}
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
        <div className={styles.row}>
          <Button type="submit" disabled={busy}>
            💾 Opslaan coëfficiënten
          </Button>
        </div>
      </form>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <Toast message={notice} onDone={() => setNotice(null)} />
    </>
  )
}

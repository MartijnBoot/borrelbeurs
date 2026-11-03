/**
 * Betalen, first on Mensen en wallets (B-12 SD3, SD13, PD10): B-06's
 * "Wallet verplicht" as a `Switch` and "Rood staan tot" as a `MoneyField`
 * (B-06 SD1-SD3; E40, E41), moved from Globale instellingen. Both are run
 * columns: a save sends the changed ones at the top level of `PATCH config`,
 * never under `params`, and nothing at all when clean ("Niets te wijzigen").
 * An emptied limit blocks the save; a 422 shows under the field it names; a
 * server change while editing keeps the input and offers "Overnemen".
 */
import { type FormEvent, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { MoneyField } from '../../components/ui/MoneyField'
import { Switch } from '../../components/ui/Switch'
import { Toast } from '../../components/ui/Toast'
import { request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import explanations from './explanations.json'
import styles from './settings.module.css'
import { faultsOf, Revision, useRunConfig } from './useRunConfig'

export function PaymentSection() {
  const { config, failed, reload } = useRunConfig()
  const server = useMemo(
    () =>
      config === null
        ? null
        : {
            wallet_required: config.run.wallet_required,
            credit_limit_cents: config.run.credit_limit_cents,
          },
    [config],
  )
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
        await request('PATCH', `/api/runs/${runId}/config`, { body: patch, schema: Revision })
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

  const limit = record.values?.credit_limit_cents ?? null
  return (
    <form onSubmit={(event) => void submit(event)}>
      {record.conflict && (
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.grid}>
        <div>
          <Switch
            label={explanations.wallet_required.name}
            info={explanations.wallet_required}
            checked={record.values?.wallet_required === true}
            onChange={(on) => record.set('wallet_required', on)}
          />
          {faults.wallet_required !== undefined && (
            <span className={styles.error}>{faults.wallet_required}</span>
          )}
        </div>
        <MoneyField
          label={explanations.credit_limit_cents.name}
          info={explanations.credit_limit_cents}
          cents={limit}
          onChange={(cents) => record.set('credit_limit_cents', cents)}
          error={
            limit === null
              ? 'Verplicht'
              : limit === 'invalid'
                ? 'Ongeldig getal'
                : faults.credit_limit_cents
          }
        />
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          Opslaan
        </Button>
        {saveError !== null && <span className={styles.error}>{saveError}</span>}
      </div>
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

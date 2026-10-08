/**
 * 🥤 Drankjes beheren (Phase 6 SD13, SD25; AC4, AC17, AC21, AC39).
 *
 * **Add:** a name, the three bounds as `MoneyField`s, and an optional bar price
 * and `a/d/s0/c`. A blank optional is left out of the body, so the server's
 * default applies (AC4); an invalid entry blocks the add.
 *
 * **Per active drink:** its name and bar price, saved as a dirty-only `PATCH`
 * ("Niets te wijzigen" when untouched), and "Verwijderen" behind
 * `ConfirmDialog` "'{name}' verwijderen?" (AC39). A removed drink is not listed.
 * The server's 409s show in Dutch.
 */
import { type FormEvent, useId, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { MoneyField } from '../../components/ui/MoneyField'
import { NumberField } from '../../components/ui/NumberField'
import { Toast } from '../../components/ui/Toast'
import { type FieldValue } from '../../lib/format'
import { HttpError, request } from '../../lib/http'
import { useEditableRecord } from '../../lib/useEditableRecord'
import styles from './settings.module.css'
import { faultsOf, Revision, type RunConfig, useRunConfig } from './useRunConfig'

const REFUSALS: Readonly<Record<string, string>> = {
  duplicate_drink_name: 'Er is al een drankje met deze naam.',
  last_active_drink: 'Het laatste actieve drankje kan niet weg.',
  drink_removed: 'Dit drankje is al verwijderd.',
  drink_not_found: 'Dit drankje bestaat niet meer.',
  run_ended: 'Deze borrel is afgelopen.',
}

function failureText(error: unknown): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  if (error instanceof HttpError && error.status === 422) return 'Controleer de ingevulde waarden.'
  return 'Opslaan mislukt. Probeer opnieuw.'
}

type Drink = RunConfig['drinks'][number]

export function DrinksSection() {
  const { config, failed, reload } = useRunConfig()
  if (config === null) {
    return <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
  }
  const runId = config.run.run_id
  return (
    <>
      <AddDrinkForm runId={runId} onDone={reload} />
      {config.drinks
        .filter((drink) => drink.active)
        .map((drink) => (
          <DrinkRow key={drink.drink_id} runId={runId} drink={drink} onDone={reload} />
        ))}
    </>
  )
}

function NameField({
  label,
  value,
  onChange,
  error,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
}) {
  const id = useId()
  return (
    <Field id={id} label={label} error={error}>
      <input
        id={id}
        className={fieldStyles.input}
        value={value}
        maxLength={40}
        aria-invalid={error !== undefined || undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  )
}

const OPTIONAL_COEFFICIENTS = ['a', 'd', 's0', 'c'] as const

interface AddDraft {
  name: string
  p_min_cents: FieldValue
  p0_cents: FieldValue
  p_max_cents: FieldValue
  bar_price_cents: FieldValue
  a: FieldValue
  d: FieldValue
  s0: FieldValue
  c: FieldValue
}

const EMPTY: AddDraft = {
  name: '',
  p_min_cents: null,
  p0_cents: null,
  p_max_cents: null,
  bar_price_cents: null,
  a: null,
  d: null,
  s0: null,
  c: null,
}

function AddDrinkForm({ runId, onDone }: { runId: number; onDone: () => Promise<void> }) {
  const [draft, setDraft] = useState<AddDraft>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [faults, setFaults] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const titleId = useId()

  const set = <K extends keyof AddDraft>(field: K, value: AddDraft[K]) =>
    setDraft((current) => ({ ...current, [field]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    const required = [draft.p_min_cents, draft.p0_cents, draft.p_max_cents]
    const optional = [draft.bar_price_cents, ...OPTIONAL_COEFFICIENTS.map((k) => draft[k])]
    if (
      draft.name.trim() === '' ||
      required.some((v) => typeof v !== 'number') ||
      optional.some((v) => v === 'invalid')
    ) {
      setError('Vul een naam en de drie prijzen in.')
      return
    }
    const body: Record<string, string | number> = {
      name: draft.name,
      p_min_cents: draft.p_min_cents as number,
      p0_cents: draft.p0_cents as number,
      p_max_cents: draft.p_max_cents as number,
    }
    for (const field of ['bar_price_cents', ...OPTIONAL_COEFFICIENTS] as const) {
      const value = draft[field]
      if (typeof value === 'number') body[field] = value
    }
    setBusy(true)
    try {
      await request('POST', `/api/runs/${runId}/drinks`, { body, schema: Revision })
      setDraft(EMPTY)
      setError(null)
      setFaults({})
      await onDone()
    } catch (failure) {
      setFaults(faultsOf(failure))
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      aria-labelledby={titleId}
      className={styles.subsection}
      onSubmit={(event) => void submit(event)}
    >
      <h3 id={titleId}>Drankje toevoegen</h3>
      <div className={styles.grid}>
        <NameField
          label="Naam"
          value={draft.name}
          onChange={(v) => set('name', v)}
          error={faults.name}
        />
        <MoneyField
          label="Min"
          cents={draft.p_min_cents}
          onChange={(v) => set('p_min_cents', v)}
          error={faults.p_min_cents}
        />
        <MoneyField
          label="Start"
          cents={draft.p0_cents}
          onChange={(v) => set('p0_cents', v)}
          error={faults.p0_cents}
        />
        <MoneyField
          label="Max"
          cents={draft.p_max_cents}
          onChange={(v) => set('p_max_cents', v)}
          error={faults.p_max_cents}
        />
        <MoneyField
          label="Barprijs"
          cents={draft.bar_price_cents}
          onChange={(v) => set('bar_price_cents', v)}
          hint="Leeg: de startprijs"
          error={draft.bar_price_cents === 'invalid' ? 'Ongeldig bedrag' : faults.bar_price_cents}
        />
        {OPTIONAL_COEFFICIENTS.map((field) => (
          <NumberField
            key={field}
            label={field}
            value={draft[field]}
            onChange={(v) => set(field, v)}
            hint="Leeg: standaard"
            error={draft[field] === 'invalid' ? 'Ongeldig getal' : faults[field]}
          />
        ))}
      </div>
      <div className={styles.row}>
        <Button type="submit" disabled={busy}>
          Toevoegen
        </Button>
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </form>
  )
}

interface RowRecord {
  name: string
  bar_price_cents: number
}

function DrinkRow({
  runId,
  drink,
  onDone,
}: {
  runId: number
  drink: Drink
  onDone: () => Promise<void>
}) {
  const server = useMemo<RowRecord>(
    () => ({ name: drink.name, bar_price_cents: drink.bar_price_cents }),
    [drink.name, drink.bar_price_cents],
  )
  const record = useEditableRecord(server)
  const [asking, setAsking] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const titleId = useId()
  const name = record.values?.name
  const price = record.values?.bar_price_cents ?? null

  async function save(event: FormEvent) {
    event.preventDefault()
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
      setError(result === 'invalid' ? 'Vul een naam en een geldige barprijs in.' : null)
    } catch (failure) {
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setAsking(false)
    setBusy(true)
    try {
      await request('DELETE', `/api/runs/${runId}/drinks/${drink.drink_id}`, {
        schema: Revision,
      })
      setError(null)
      await onDone()
    } catch (failure) {
      setError(failureText(failure))
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
        <p className={styles.row} role="alert">
          Serverwaarden gewijzigd — overnemen?
          <Button onClick={record.takeServer}>Overnemen</Button>
        </p>
      )}
      <div className={styles.row}>
        <NameField
          label="Naam"
          value={typeof name === 'string' ? name : ''}
          onChange={(v) => record.set('name', v.trim() === '' ? null : v)}
        />
        <MoneyField
          label="Barprijs"
          cents={price}
          onChange={(v) => record.set('bar_price_cents', v)}
        />
        <Button type="submit" disabled={busy}>
          Opslaan
        </Button>
        <Button disabled={busy} onClick={() => setAsking(true)}>
          Verwijderen
        </Button>
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={asking}
        message={`'${drink.name}' verwijderen?`}
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => void remove()}
        onCancel={() => setAsking(false)}
      />
      <Toast message={notice} onDone={() => setNotice(null)} />
    </form>
  )
}

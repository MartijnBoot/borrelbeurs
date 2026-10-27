/**
 * Toegangssleutels (Phase 6 SD30; AC36, AC38, AC39).
 *
 * - **The list:** every key's label, role, created, last used and
 *   Actief/Ingetrokken; never a secret.
 * - **"Nieuwe sleutel"** (role, label 1–100) posts `/api/keys` and shows the
 *   returned key exactly once, grouped as `K7M-4QX-9PR`, larger and monospaced
 *   so it can be read aloud (B-08 SD8). "Sluiten" drops it from component
 *   state, so it is gone from the DOM (AC36).
 * - **"Kopieer"** writes it to the clipboard. Where that fails -- a plain-HTTP
 *   page has no `navigator.clipboard` (D-50), or `writeText` rejects -- it
 *   selects the key's text instead and says so (B-08 SD9). It never throws.
 * - **"Intrekken"** sits behind `ConfirmDialog` "'{label}' intrekken?" (AC39);
 *   the server's `last_admin_key` refusal shows in Dutch (AC38).
 */
import { type FormEvent, useCallback, useEffect, useId, useRef, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Field } from '../../components/ui/Field'
import fieldStyles from '../../components/ui/Field.module.css'
import { Select } from '../../components/ui/Select'
import { HttpError, request } from '../../lib/http'
import { formatWhen } from '../../lib/time'
import styles from './KeysSection.module.css'

const Role = z.enum(['display', 'bar', 'admin', 'kassa'])
type Role = z.infer<typeof Role>

const KeyInfo = z.object({
  key_id: z.number(),
  label: z.string(),
  role: Role,
  created_at: z.string(),
  last_used_at: z.string().nullable(),
  revoked: z.boolean(),
})
type KeyInfo = z.infer<typeof KeyInfo>

const CreatedKey = z.object({ key_id: z.number(), key: z.string() })

const ROLES = [
  { value: 'display', label: 'Scherm' },
  { value: 'bar', label: 'Bar' },
  { value: 'admin', label: 'Beheer' },
  { value: 'kassa', label: 'Kassa' },
] as const satisfies readonly { value: Role; label: string }[]

const ROLE_LABEL: Readonly<Record<Role, string>> = Object.fromEntries(
  ROLES.map((role) => [role.value, role.label]),
) as Record<Role, string>

const REFUSALS: Readonly<Record<string, string>> = {
  last_admin_key: 'Dit is de laatste beheerderssleutel; die kan niet worden ingetrokken.',
  key_not_found: 'Deze sleutel bestaat niet meer.',
}

function failureText(error: unknown, fallback: string): string {
  if (error instanceof HttpError && REFUSALS[error.code] !== undefined) return REFUSALS[error.code]
  if (error instanceof HttpError && error.status === 422) return 'Kies een rol en vul een label in.'
  return fallback
}

export function KeysSection() {
  const [keys, setKeys] = useState<KeyInfo[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [role, setRole] = useState<Role>('bar')
  const [label, setLabel] = useState('')
  const [secret, setSecret] = useState<string | null>(null)
  const [copyFailed, setCopyFailed] = useState(false)
  const shownKey = useRef<HTMLElement>(null)
  const [revoking, setRevoking] = useState<KeyInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const labelId = useId()

  const reload = useCallback(
    () =>
      request('GET', '/api/keys', { schema: z.array(KeyInfo) }).then(
        (list) => {
          setKeys(list)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    void reload()
  }, [reload])

  async function create(event: FormEvent) {
    event.preventDefault()
    if (label.trim() === '') {
      setError('Kies een rol en vul een label in.')
      return
    }
    setBusy(true)
    try {
      const created = await request('POST', '/api/keys', {
        body: { role, label },
        schema: CreatedKey,
      })
      setSecret(created.key)
      setCopyFailed(false)
      setLabel('')
      setError(null)
      await reload()
    } catch (caught) {
      setError(failureText(caught, 'Aanmaken mislukt. Probeer opnieuw.'))
    } finally {
      setBusy(false)
    }
  }

  async function copy(key: string) {
    try {
      // A missing `navigator.clipboard` throws here, inside the `try` (D-50).
      await navigator.clipboard.writeText(key)
      setCopyFailed(false)
    } catch {
      if (shownKey.current !== null) window.getSelection()?.selectAllChildren(shownKey.current)
      setCopyFailed(true)
    }
  }

  function close() {
    setSecret(null)
    setCopyFailed(false)
  }

  async function revoke(key: KeyInfo) {
    setRevoking(null)
    setBusy(true)
    try {
      await request('DELETE', `/api/keys/${key.key_id}`, { schema: z.unknown() })
      setError(null)
      await reload()
    } catch (caught) {
      setError(failureText(caught, 'Intrekken mislukt. Probeer opnieuw.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {keys === null ? (
        <p className={styles.muted}>{failed ? 'Verbindingsfout. Probeer opnieuw.' : 'Laden…'}</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Label</th>
              <th>Rol</th>
              <th>Aangemaakt</th>
              <th>Laatst gebruikt</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.key_id}>
                <td>{key.label}</td>
                <td>{ROLE_LABEL[key.role]}</td>
                <td>{formatWhen(Date.parse(key.created_at))}</td>
                <td>
                  {key.last_used_at === null ? 'Nooit' : formatWhen(Date.parse(key.last_used_at))}
                </td>
                <td>{key.revoked ? 'Ingetrokken' : 'Actief'}</td>
                <td>
                  {!key.revoked && (
                    <Button disabled={busy} onClick={() => setRevoking(key)}>
                      Intrekken
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form className={styles.row} onSubmit={(event) => void create(event)}>
        <Select label="Rol" value={role} options={ROLES} onChange={setRole} />
        <Field id={labelId} label="Label">
          <input
            id={labelId}
            className={fieldStyles.input}
            value={label}
            maxLength={100}
            onChange={(event) => setLabel(event.target.value)}
          />
        </Field>
        <Button type="submit" disabled={busy}>
          Nieuwe sleutel
        </Button>
      </form>

      {secret !== null && (
        <div className={styles.secret}>
          <code ref={shownKey} className={styles.key}>
            {secret}
          </code>
          <p className={styles.muted}>Wordt maar één keer getoond</p>
          {copyFailed && (
            <p className={styles.muted} role="status">
              Kopiëren lukt hier niet. De sleutel is geselecteerd: kopieer hem zelf.
            </p>
          )}
          <div className={styles.row}>
            <Button onClick={() => void copy(secret)}>Kopieer</Button>
            <Button onClick={close}>Sluiten</Button>
          </div>
        </div>
      )}

      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={revoking !== null}
        message={`'${revoking?.label ?? ''}' intrekken?`}
        confirmLabel="Bevestigen"
        cancelLabel="Annuleren"
        onConfirm={() => revoking !== null && void revoke(revoking)}
        onCancel={() => setRevoking(null)}
      />
    </>
  )
}

/**
 * The login form, ported from v1's `login.html` with its strings verbatim
 * (PD17). One failure message for a wrong and an unknown key alike, so the
 * page never reveals whether a key exists (AC21).
 *
 * After login (SD12): `next` if it is one of the session's `allowed_routes`,
 * otherwise the first of them, the role's landing route (SD4).
 */
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import logo from '../../assets/logo.png'
import { HttpError, request } from '../../lib/http'
import styles from './LoginPage.module.css'
import { Me, useSession } from './useSession'

const INVALID_KEY = 'Ongeldige toegangscode.'
const NETWORK_ERROR = 'Verbindingsfout. Probeer opnieuw.'
const RATE_LIMITED = 'Te veel pogingen. Probeer het over een minuut opnieuw.'

function failureText(error: unknown): string {
  if (error instanceof HttpError) {
    if (error.status === 401 || error.status === 422) return INVALID_KEY
    if (error.status === 429) return RATE_LIMITED
  }
  return NETWORK_ERROR
}

export function LoginPage() {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { signedIn } = useSession()

  async function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const me = await request('POST', '/api/auth/login', { body: { key: trimmed }, schema: Me })
      signedIn(me)
      const next = params.get('next')
      const landing =
        next !== null && me.allowed_routes.includes(next) ? next : me.allowed_routes[0]
      navigate(landing ?? '/', { replace: true })
    } catch (failure) {
      setError(failureText(failure))
      setBusy(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <form className={styles.card} onSubmit={submit}>
        <img src={logo} alt="Beurs Borrel" className={styles.logo} />
        <h1>Welkom</h1>
        <div className={styles.sub}>Voer je toegangscode in.</div>
        <label htmlFor="key">Toegangscode</label>
        <input
          id="key"
          type="text"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
        <button type="submit" disabled={busy}>
          Inloggen
        </button>
        {error !== null && (
          <div className={styles.err} role="alert">
            {error}
          </div>
        )}
      </form>
    </div>
  )
}

/**
 * Sign-up (B-05 SD3, SD6; AC2-AC4, AC6, AC7): a name and the sign-up code, the
 * code filled in from `?code=` (the poster's link).
 *
 * The name is checked on blur, once per distinct (name, code) and only when
 * both are filled (PD14): the check shares the sign-up's 5-a-minute limiter,
 * so never per keystroke. A taken name offers the server's suggestions as
 * buttons; picking one fills the field and signs up with it.
 */
import { type FormEvent, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Field } from '../../components/ui/Field'
import { HttpError } from '../../lib/http'
import { nameCheck, signUp, takenSuggestions, type Wallet } from './api'
import styles from './PlayerPage.module.css'

export const NAME_MAX = 40

const TEXTS = {
  signup_code_invalid: 'Onjuiste aanmeldcode.',
  signup_closed: 'Aanmelden is nu gesloten.',
  name: 'Kies een naam van 1 tot 40 tekens.',
  taken: 'Die naam is al bezet. Kies een andere:',
  network: 'Verbindingsfout. Probeer opnieuw.',
} as const

function failureText(error: unknown): string {
  if (error instanceof HttpError) {
    if (error.code === 'signup_code_invalid') return TEXTS.signup_code_invalid
    if (error.code === 'signup_closed') return TEXTS.signup_closed
    if (error.status === 422) return TEXTS.name
    if (error.status === 429) {
      const wait = error.retryAfter ?? 60
      return `Te veel pogingen. Probeer het over ${wait} seconden opnieuw.`
    }
  }
  return TEXTS.network
}

export function SignupForm({ onSignedUp }: { onSignedUp: (wallet: Wallet) => void }) {
  const [params] = useSearchParams()
  const [name, setName] = useState('')
  const [code, setCode] = useState(() => params.get('code') ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<readonly string[] | null>(null)
  const checked = useRef<string | null>(null)

  async function check() {
    const typed = { name: name.trim(), code: code.trim() }
    const key = JSON.stringify(typed)
    if (!typed.name || !typed.code || checked.current === key) return
    checked.current = key
    try {
      setSuggestions(await nameCheck(typed.name, typed.code))
      setError(null)
    } catch (failure) {
      setSuggestions(null)
      setError(failureText(failure))
    }
  }

  async function submit(chosen: string) {
    if (!chosen.trim() || chosen.trim().length > NAME_MAX) {
      setError(TEXTS.name)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onSignedUp(await signUp(chosen, code))
    } catch (failure) {
      const taken = takenSuggestions(failure)
      setSuggestions(taken)
      setError(taken === null ? failureText(failure) : null)
      setBusy(false)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void submit(name)
  }

  function pick(suggestion: string) {
    setName(suggestion)
    void submit(suggestion)
  }

  return (
    <form className={styles.card} onSubmit={onSubmit}>
      <h1>Wallet aanmaken</h1>
      <Field id="wallet-name" label="Naam">
        <input
          id="wallet-name"
          type="text"
          autoComplete="nickname"
          maxLength={NAME_MAX}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => void check()}
        />
      </Field>
      <Field id="wallet-code" label="Aanmeldcode">
        <input
          id="wallet-code"
          type="text"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          onBlur={() => void check()}
        />
      </Field>
      {suggestions !== null && (
        <div className={styles.suggestions} role="group" aria-label="Vrije namen">
          <p>{TEXTS.taken}</p>
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button" disabled={busy} onClick={() => pick(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      )}
      <button type="submit" className={styles.primary} disabled={busy}>
        Aanmelden
      </button>
      {error !== null && (
        <div className={styles.err} role="alert">
          {error}
        </div>
      )}
    </form>
  )
}

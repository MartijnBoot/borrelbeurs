import { useEffect, useState } from 'react'

type HealthStatus =
  | { state: 'loading' }
  | { state: 'ok'; body: string }
  | { state: 'error'; message: string }

/**
 * Placeholder shell (plan T6). Its only job is proving the SPA is served from
 * the same origin as the API: fetch a relative path, no base URL, no CORS.
 * Phase 4 replaces this with the real app shell (routes, providers, layout).
 */
export function App() {
  const [health, setHealth] = useState<HealthStatus>({ state: 'loading' })

  useEffect(() => {
    let cancelled = false

    fetch('/healthz')
      .then(async (response) => {
        const body = await response.text()
        if (!cancelled) {
          if (!response.ok) throw new Error(`${response.status} ${body}`)
          setHealth({ state: 'ok', body })
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHealth({ state: 'error', message: String(error) })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main>
      <h1>BorrelBeurs</h1>
      <p>
        /healthz:{' '}
        {health.state === 'loading' && 'loading…'}
        {health.state === 'ok' && health.body}
        {health.state === 'error' && `error: ${health.message}`}
      </p>
    </main>
  )
}

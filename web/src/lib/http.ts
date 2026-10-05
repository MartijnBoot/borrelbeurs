/**
 * The one HTTP wrapper: JSON in, a Zod-validated body out (PD12).
 *
 * Success bodies are parsed with the caller's schema. Failures are parsed
 * with the single `ErrorEnvelope` schema -- the app's own
 * `{error: {code, message, …}}` (`app/core/errors.py`) -- never with the
 * generated OpenAPI error types, which describe a shape the server does not
 * send. Anything that fits neither is an `HttpError` with code
 * `invalid_response`, so a caller never holds an unvalidated body.
 */
import { z } from 'zod'

const ErrorEnvelope = z.object({
  error: z.looseObject({ code: z.string(), message: z.string() }),
})

export class HttpError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.code = code
  }
}

let onUnauthenticated: (() => void) | null = null

/** Registers what a 401 does (SD12); T16 wires it to navigation. */
export function setOnUnauthenticated(hook: (() => void) | null): void {
  onUnauthenticated = hook
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

export async function request<T>(
  method: Method,
  path: string,
  { body, schema }: { body?: unknown; schema: z.ZodType<T> },
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = await readJson(response)

  if (!response.ok) {
    if (response.status === 401) onUnauthenticated?.()
    const envelope = ErrorEnvelope.safeParse(payload)
    if (envelope.success) {
      throw new HttpError(response.status, envelope.data.error.code, envelope.data.error.message)
    }
    throw new HttpError(response.status, 'invalid_response', `HTTP ${response.status}`)
  }

  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new HttpError(response.status, 'invalid_response', 'the response body is not valid')
  }
  return parsed.data
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return undefined
  }
}

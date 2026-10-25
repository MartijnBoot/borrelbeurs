/**
 * The one HTTP wrapper: JSON in, a Zod-validated body out (PD12).
 *
 * Success bodies are parsed with the caller's schema. Failures are parsed
 * with the single `ErrorEnvelope` schema -- the app's own
 * `{error: {code, message, …}}` (`app/core/errors.py`) -- never with the
 * generated OpenAPI error types, which describe a shape the server does not
 * send. Anything that fits neither is an `HttpError` with code
 * `invalid_response`, so a caller never holds an unvalidated body.
 *
 * The envelope's extra fields survive as `HttpError.details` (Phase 5 PD6): a
 * 409 `price_changed` carries its `version` and `prices` there. A network
 * failure or an aborted `signal` (a timeout) is not an HTTP answer, so it
 * rejects with the original error, never an `HttpError`. A `Retry-After`
 * header survives as `HttpError.retryAfter` (B-05: the sign-up's 429 text).
 */
import { z } from 'zod'

const ErrorEnvelope = z.object({
  error: z.looseObject({ code: z.string(), message: z.string() }),
})

export class HttpError extends Error {
  readonly status: number
  readonly code: string
  /** The error envelope's fields beyond `code` and `message`; empty without one. */
  readonly details: Readonly<Record<string, unknown>>
  /** A `Retry-After` in whole seconds (a 429's, B-05 PD15), else `null`. */
  readonly retryAfter: number | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: Readonly<Record<string, unknown>> = {},
    retryAfter: number | null = null,
  ) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.code = code
    this.details = details
    this.retryAfter = retryAfter
  }
}

let onUnauthenticated: (() => void) | null = null

/** Registers what a 401 does (SD12); T16 wires it to navigation. */
export function setOnUnauthenticated(hook: (() => void) | null): void {
  onUnauthenticated = hook
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/**
 * A JSON `body`, or a multipart `formData` (Phase 6 PD1: an image upload), never both.
 * With `formData` no `Content-Type` is set here: the browser adds the multipart
 * boundary itself.
 */
type Payload = { body?: unknown; formData?: never } | { body?: never; formData: FormData }

export async function request<T>(
  method: Method,
  path: string,
  options: Payload & {
    schema: z.ZodType<T>
    headers?: Readonly<Record<string, string>>
    signal?: AbortSignal
  },
): Promise<T> {
  const { body, formData, schema, headers, signal } = options
  const json = body !== undefined
  const sent = { ...(json ? { 'Content-Type': 'application/json' } : {}), ...headers }
  const response = await fetch(path, {
    method,
    headers: Object.keys(sent).length === 0 ? undefined : sent,
    body: json ? JSON.stringify(body) : formData,
    signal,
  })
  const payload = await readJson(response)

  if (!response.ok) {
    if (response.status === 401) onUnauthenticated?.()
    const retryAfter = seconds(response.headers.get('Retry-After'))
    const envelope = ErrorEnvelope.safeParse(payload)
    if (envelope.success) {
      const { code, message, ...details } = envelope.data.error
      throw new HttpError(response.status, code, message, details, retryAfter)
    }
    throw new HttpError(
      response.status,
      'invalid_response',
      `HTTP ${response.status}`,
      {},
      retryAfter,
    )
  }

  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new HttpError(response.status, 'invalid_response', 'the response body is not valid')
  }
  return parsed.data
}

/** `Retry-After` as delay-seconds; its HTTP-date form is not one this server sends. */
function seconds(header: string | null): number | null {
  return header !== null && /^\d+$/.test(header.trim()) ? Number(header.trim()) : null
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return undefined
  }
}

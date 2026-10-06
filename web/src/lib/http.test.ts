import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { HttpError, request, setOnUnauthenticated } from './http'

const Me = z.object({ role: z.string() })

function respond(status: number, body: unknown): Response {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return new Response(text, { status, headers: { 'Content-Type': 'application/json' } })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  setOnUnauthenticated(null)
})

async function rejection(promise: Promise<unknown>): Promise<HttpError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof HttpError) return error
    throw error
  }
  throw new Error('expected the request to fail')
}

describe('request', () => {
  it('parses a success body with the given schema', async () => {
    fetchMock.mockResolvedValue(respond(200, { role: 'admin' }))
    await expect(request('GET', '/api/auth/me', { schema: Me })).resolves.toEqual({
      role: 'admin',
    })
  })

  it('sends a JSON body with the method', async () => {
    fetchMock.mockResolvedValue(respond(200, { role: 'admin' }))
    await request('PUT', '/api/theme', { body: { preset: 'rood' }, schema: Me })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/theme')
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"preset":"rood"}')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('parses the error envelope into an HttpError', async () => {
    fetchMock.mockResolvedValue(
      respond(403, { error: { code: 'forbidden', message: 'not allowed', extra: 1 } }),
    )
    const error = await rejection(request('PUT', '/api/theme', { body: {}, schema: Me }))
    expect(error.status).toBe(403)
    expect(error.code).toBe('forbidden')
    expect(error.message).toBe('not allowed')
  })

  it('calls the unauthenticated hook exactly once on a 401', async () => {
    const hook = vi.fn()
    setOnUnauthenticated(hook)
    fetchMock.mockResolvedValue(
      respond(401, { error: { code: 'unauthenticated', message: 'log in' } }),
    )
    const error = await rejection(request('GET', '/api/auth/me', { schema: Me }))
    expect(error.status).toBe(401)
    expect(hook).toHaveBeenCalledTimes(1)
  })

  it('does not call the hook on other failures', async () => {
    const hook = vi.fn()
    setOnUnauthenticated(hook)
    fetchMock.mockResolvedValue(respond(403, { error: { code: 'forbidden', message: 'no' } }))
    await rejection(request('GET', '/api/auth/me', { schema: Me }))
    expect(hook).not.toHaveBeenCalled()
  })

  it('makes a malformed success body a typed error', async () => {
    fetchMock.mockResolvedValue(respond(200, { role: 42 }))
    const error = await rejection(request('GET', '/api/auth/me', { schema: Me }))
    expect(error.status).toBe(200)
    expect(error.code).toBe('invalid_response')
  })

  it('makes a non-JSON success body a typed error', async () => {
    fetchMock.mockResolvedValue(respond(200, '<html>'))
    const error = await rejection(request('GET', '/api/auth/me', { schema: Me }))
    expect(error.code).toBe('invalid_response')
  })

  it('makes a failure without the envelope a typed error', async () => {
    fetchMock.mockResolvedValue(respond(502, 'Bad Gateway'))
    const error = await rejection(request('GET', '/api/auth/me', { schema: Me }))
    expect(error.status).toBe(502)
    expect(error.code).toBe('invalid_response')
    expect(error.details).toEqual({})
  })

  it('sends custom headers alongside the JSON content type', async () => {
    fetchMock.mockResolvedValue(respond(201, { role: 'bar' }))
    await request('POST', '/api/orders', {
      body: { a: 1 },
      headers: { 'Idempotency-Key': 'k-0001' },
      schema: Me,
    })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Idempotency-Key')).toBe('k-0001')
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('passes the signal to fetch', async () => {
    fetchMock.mockResolvedValue(respond(200, { role: 'bar' }))
    const controller = new AbortController()
    await request('GET', '/api/auth/me', { schema: Me, signal: controller.signal })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.signal).toBe(controller.signal)
  })

  it('rejects an aborted request with the abort error, not an HttpError', async () => {
    fetchMock.mockImplementation((_path: string, init: RequestInit) =>
      Promise.reject(init.signal?.reason),
    )
    const controller = new AbortController()
    controller.abort(new DOMException('timed out', 'TimeoutError'))
    const promise = request('GET', '/api/auth/me', { schema: Me, signal: controller.signal })
    await expect(promise).rejects.toMatchObject({ name: 'TimeoutError' })
    await expect(promise).rejects.not.toBeInstanceOf(HttpError)
  })

  it('rejects a network failure with the original error', async () => {
    const failure = new TypeError('Failed to fetch')
    fetchMock.mockRejectedValue(failure)
    await expect(request('GET', '/api/auth/me', { schema: Me })).rejects.toBe(failure)
  })

  it("keeps the envelope's extra fields as details, so a 409 carries its prices", async () => {
    const prices = [{ drink_id: 1, price_cents: 270 }]
    fetchMock.mockResolvedValue(
      respond(409, {
        error: { code: 'price_changed', message: 'moved', version: 42, prices },
      }),
    )
    const error = await rejection(request('POST', '/api/orders', { body: {}, schema: Me }))
    expect(error.status).toBe(409)
    expect(error.code).toBe('price_changed')
    expect(error.details.version).toBe(42)
    expect(error.details.prices).toEqual(prices)
  })
})

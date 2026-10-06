// postOrder against a stubbed fetch (Phase 5 T7): the header, the receipt,
// the 409 body, and the errors the intent machine classifies.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError, setOnUnauthenticated } from '../../../lib/http'
import { postOrder } from './orders'

const BODY = Object.freeze({
  quote_version: 7,
  lines: Object.freeze([Object.freeze({ drink_id: 1, qty: 1, unit_price_cents: 250 })]),
})

const RECEIPT = {
  order_id: 3,
  version: 8,
  wall_ts_ms: 1_000,
  quote_version: 7,
  lines: [{ drink_id: 1, qty: 1, unit_price_cents: 250, line_total_cents: 250 }],
  total_cents: 250,
}

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
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

describe('postOrder', () => {
  it('posts the body with the Idempotency-Key header and a timeout signal', async () => {
    fetchMock.mockResolvedValue(respond(201, RECEIPT))
    await postOrder({ key: 'key-0001', body: BODY })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/orders')
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('key-0001')
    expect(init.body).toBe(JSON.stringify(BODY))
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })

  it('parses a receipt as accepted (201 and a 200 replay alike)', async () => {
    fetchMock.mockResolvedValueOnce(respond(201, RECEIPT))
    fetchMock.mockResolvedValueOnce(respond(200, RECEIPT))
    for (let i = 0; i < 2; i++) {
      await expect(postOrder({ key: 'key-0001', body: BODY })).resolves.toEqual({
        kind: 'accepted',
        receipt: RECEIPT,
      })
    }
  })

  it('parses a 409 price_changed into its body', async () => {
    const error = {
      code: 'price_changed',
      message: 'prices changed since the quote',
      version: 9,
      prices: [{ drink_id: 1, price_cents: 270 }],
    }
    fetchMock.mockResolvedValue(respond(409, { error }))
    await expect(postOrder({ key: 'key-0001', body: BODY })).resolves.toEqual({
      kind: 'price_changed',
      body: { version: 9, prices: [{ drink_id: 1, price_cents: 270 }] },
    })
  })

  it('a malformed 409 is a typed error', async () => {
    const error = { code: 'price_changed', message: 'x', version: 'nine' }
    fetchMock.mockResolvedValue(respond(409, { error }))
    const rejected = await postOrder({ key: 'key-0001', body: BODY }).catch((e: unknown) => e)
    expect(rejected).toBeInstanceOf(HttpError)
    expect(rejected).toMatchObject({ status: 409, code: 'invalid_response' })
  })

  it('a malformed receipt is a typed error', async () => {
    fetchMock.mockResolvedValue(respond(201, { ...RECEIPT, total_cents: '250' }))
    const rejected = await postOrder({ key: 'key-0001', body: BODY }).catch((e: unknown) => e)
    expect(rejected).toMatchObject({ status: 201, code: 'invalid_response' })
  })

  it('other errors reject as they come: a 503 HttpError, a network TypeError', async () => {
    const error = { code: 'persistence_unavailable', message: 'down' }
    fetchMock.mockResolvedValueOnce(respond(503, { error }))
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(postOrder({ key: 'key-0001', body: BODY })).rejects.toMatchObject({ status: 503 })
    await expect(postOrder({ key: 'key-0001', body: BODY })).rejects.toBeInstanceOf(TypeError)
  })

  it('a 401 sends the page to login (SD8, SD12)', async () => {
    const hook = vi.fn()
    setOnUnauthenticated(hook)
    fetchMock.mockResolvedValue(respond(401, { error: { code: 'unauthenticated', message: '' } }))
    await expect(postOrder({ key: 'key-0001', body: BODY })).rejects.toMatchObject({ status: 401 })
    expect(hook).toHaveBeenCalledOnce()
  })
})

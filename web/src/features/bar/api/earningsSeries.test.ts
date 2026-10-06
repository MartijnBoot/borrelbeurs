// fetchEarningsSeries against a stubbed fetch (Phase 5 T13).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '../../../lib/http'
import { fetchEarningsSeries } from './earningsSeries'

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

afterEach(() => vi.unstubAllGlobals())

describe('fetchEarningsSeries', () => {
  it('GETs the series and parses a valid body', async () => {
    const body = [
      { t_ms: 60_000, cum_revenue_cents: 250 },
      { t_ms: 120_000, cum_revenue_cents: 770 },
    ]
    fetchMock.mockResolvedValue(respond(200, body))
    await expect(fetchEarningsSeries()).resolves.toEqual(body)
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/earnings/series')
    expect(init.method).toBe('GET')
  })

  it('gives [] on 409 no_live_run', async () => {
    fetchMock.mockResolvedValue(respond(409, { error: { code: 'no_live_run', message: '' } }))
    await expect(fetchEarningsSeries()).resolves.toEqual([])
  })

  it('a malformed body is a typed error', async () => {
    fetchMock.mockResolvedValue(respond(200, [{ t_ms: '60000', cum_revenue_cents: 1 }]))
    const error = await fetchEarningsSeries().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(HttpError)
    expect(error).toMatchObject({ code: 'invalid_response' })
  })

  it('other errors reject', async () => {
    fetchMock.mockResolvedValue(respond(403, { error: { code: 'forbidden', message: '' } }))
    await expect(fetchEarningsSeries()).rejects.toMatchObject({ status: 403 })
  })
})

// @vitest-environment jsdom
// useProfiles (B-04 PD13, AC22): the profile list, `[]` plus `failed` when it cannot be
// fetched, and refetched by every mounted copy when a save, overwrite or delete bumps it.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { bumpProfiles, useProfiles } from './useProfiles'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const WILD = {
  profile_id: 2,
  name: 'Wilde beurs',
  saved_at: '2026-10-24T12:05:00Z',
  source_run_name: 'Proef',
}
const CALM = { ...WILD, profile_id: 1, name: 'rustig', source_run_name: 'Vrijmibo' }

let answer: () => Response

beforeEach(() => {
  answer = () => json(200, [CALM, WILD])
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(answer())),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useProfiles', () => {
  it('is the parsed list, in the order the server sent it', async () => {
    const { result } = renderHook(() => useProfiles())

    await waitFor(() => expect(result.current.profiles).toEqual([CALM, WILD]))
    expect(result.current.failed).toBe(false)
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe('/api/profiles')
  })

  it('is empty and failed when the list cannot be fetched', async () => {
    answer = () => json(500, { error: { code: 'internal', message: 'boom' } })

    const { result } = renderHook(() => useProfiles())

    await waitFor(() => expect(result.current.failed).toBe(true))
    expect(result.current.profiles).toEqual([])
  })

  it('a bump makes every mounted copy refetch', async () => {
    const first = renderHook(() => useProfiles())
    const second = renderHook(() => useProfiles())
    await waitFor(() => expect(second.result.current.profiles).toEqual([CALM, WILD]))

    answer = () => json(200, [WILD])
    act(() => bumpProfiles())

    await waitFor(() => expect(second.result.current.profiles).toEqual([WILD]))
    expect(first.result.current.profiles).toEqual([WILD])
  })
})

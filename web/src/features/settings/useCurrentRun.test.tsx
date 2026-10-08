// @vitest-environment jsdom
// useCurrentRun (Phase 6 SD4, SD7; AC24): every section edits the same current run, and
// a draft write broadcasts nothing, so one section's create or reload must reach the rest.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { useCurrentRun } from './useCurrentRun'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const noRun = () => json(404, { error: { code: 'no_current_run', message: 'none' } })
const draft = { run_id: 7, name: 'Vrijmibo', status: 'draft' as const }

let answer: () => Response

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  answer = noRun
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(answer())),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useCurrentRun', () => {
  it('a run set by one section reaches the others without a websocket message', async () => {
    const first = renderHook(() => useCurrentRun())
    const second = renderHook(() => useCurrentRun())
    await waitFor(() => expect(second.result.current.run).toBeNull())

    answer = () => json(200, draft)
    act(() => first.result.current.setRun(draft))

    await waitFor(() => expect(second.result.current.run).toEqual(draft))
  })

  it('a reload by one section reaches the others', async () => {
    const first = renderHook(() => useCurrentRun())
    const second = renderHook(() => useCurrentRun())
    await waitFor(() => expect(second.result.current.run).toBeNull())

    answer = () => json(200, draft)
    await act(() => first.result.current.reload())

    await waitFor(() => expect(second.result.current.run).toEqual(draft))
  })
})

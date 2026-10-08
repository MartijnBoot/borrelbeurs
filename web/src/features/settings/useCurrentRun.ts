/**
 * "The current run" `/settings` edits (Phase 6 SD4, PD2): `GET /api/runs/current`
 * -- the live run, else the draft -- or `null` with neither (404
 * `no_current_run`). `undefined` while loading. It refetches when the store's
 * run, snapshot or `config` changes, so a go-live or a broadcast shows here.
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { z } from 'zod'
import { HttpError, request } from '../../lib/http'
import { useExchange } from '../exchange'

export const CurrentRun = z.object({
  run_id: z.number().int(),
  name: z.string(),
  status: z.enum(['draft', 'live', 'ended']),
})
export type CurrentRun = z.infer<typeof CurrentRun>

export async function fetchCurrentRun(): Promise<CurrentRun | null> {
  try {
    return await request('GET', '/api/runs/current', { schema: CurrentRun })
  } catch (error) {
    if (error instanceof HttpError && error.code === 'no_current_run') return null
    throw error
  }
}

/**
 * Every section reads the current run on its own, and a draft write broadcasts
 * nothing (SD7). So a section that changes the run, or reloads it, bumps this
 * version and every mounted section refetches.
 */
let version = 0
const listeners = new Set<() => void>()

function bumpVersion() {
  version += 1
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useCurrentRun() {
  const [run, setRun] = useState<CurrentRun | null | undefined>(undefined)
  const [failed, setFailed] = useState(false)
  const liveRunId = useExchange((s) => s.run?.run_id ?? null)
  const snapshotGen = useExchange((s) => s.snapshotGen)
  const params = useExchange((s) => s.params)
  const shared = useSyncExternalStore(subscribe, () => version)

  const fetchRun = useCallback(
    () =>
      fetchCurrentRun().then(
        (current) => {
          setRun(current)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    void fetchRun()
  }, [fetchRun, liveRunId, snapshotGen, params, shared])

  const reload = useCallback(async () => {
    await fetchRun()
    bumpVersion()
  }, [fetchRun])

  const replace = useCallback((next: CurrentRun | null) => {
    setRun(next)
    bumpVersion()
  }, [])

  return { run, setRun: replace, reload, failed }
}

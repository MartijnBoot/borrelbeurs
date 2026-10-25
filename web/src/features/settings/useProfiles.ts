/**
 * The setting profiles (B-04 SD12, PD13): `GET /api/profiles`, by case-folded
 * name as the server sorts it, with no values. `[]` while loading, and `[]` plus
 * `failed` when the list cannot be fetched, so the "Nieuwe borrel" form still
 * offers "—" (AC22).
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { z } from 'zod'
import { request } from '../../lib/http'

export const Profile = z.object({
  profile_id: z.number().int(),
  name: z.string(),
  saved_at: z.string(),
  source_run_name: z.string(),
})
export type Profile = z.infer<typeof Profile>

/**
 * Profielen and the "Nieuwe borrel" form each read the list, and a profile write
 * broadcasts nothing. So every save, overwrite and delete bumps this version and
 * every mounted list refetches, as `useCurrentRun` does for the run.
 */
let version = 0
const listeners = new Set<() => void>()

export function bumpProfiles() {
  version += 1
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useProfiles() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [failed, setFailed] = useState(false)
  const shared = useSyncExternalStore(subscribe, () => version)

  const fetchProfiles = useCallback(
    () =>
      request('GET', '/api/profiles', { schema: z.array(Profile) }).then(
        (listed) => {
          setProfiles(listed)
          setFailed(false)
        },
        () => {
          setProfiles([])
          setFailed(true)
        },
      ),
    [],
  )

  useEffect(() => {
    void fetchProfiles()
  }, [fetchProfiles, shared])

  return { profiles, failed }
}

/**
 * The runs "Kopieer drankjes uit" offers (Phase 7 SD4, PD16): `GET
 * /api/analytics/runs` without its drafts. A small schema of its own -- only
 * what the select needs -- so `features/settings` never imports
 * `features/analytics`.
 */
import { z } from 'zod'
import { request } from '../../lib/http'

const PastRun = z.object({
  run_id: z.number().int(),
  name: z.string(),
  status: z.enum(['draft', 'live', 'ended']),
})
export type PastRun = z.infer<typeof PastRun>

export async function fetchPastRuns(): Promise<PastRun[]> {
  const runs = await request('GET', '/api/analytics/runs', { schema: z.array(PastRun) })
  return runs.filter((run) => run.status !== 'draft')
}

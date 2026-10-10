/**
 * The run list and a run's delete (Phase 7 SD3, SD10, SD12; PD11, PD12).
 *
 * `GET /api/analytics/runs`: every run, newest first, with its totals in
 * integer cents; `duration_ms` only for an ended run. `DELETE
 * /api/runs/{run_id}` with the typed name answers 204 with no body.
 */
import { z } from 'zod'
import { request } from '../../../lib/http'

export const AnalyticsRun = z.object({
  run_id: z.number().int(),
  name: z.string(),
  status: z.enum(['draft', 'live', 'ended']),
  t0_ms: z.number().int().nullable(),
  ended_at_ms: z.number().int().nullable(),
  duration_ms: z.number().int().nullable(),
  qty: z.number().int(),
  revenue_cents: z.number().int(),
  bar_price_total_cents: z.number().int(),
})
export type AnalyticsRun = z.infer<typeof AnalyticsRun>

export function fetchRuns(): Promise<AnalyticsRun[]> {
  return request('GET', '/api/analytics/runs', { schema: z.array(AnalyticsRun) })
}

export async function deleteRun(runId: number, confirmName: string): Promise<void> {
  await request('DELETE', `/api/runs/${runId}`, {
    body: { confirm_name: confirmName },
    schema: z.undefined(),
  })
}

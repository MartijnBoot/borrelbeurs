/**
 * `GET /api/earnings/series` (Phase 5 SD16): the live run's cumulative
 * revenue at 60 s bucket ends, Zod-validated. With no live run (409
 * `no_live_run`) there is no history to draw, so it is `[]`.
 */
import { z } from 'zod'
import { HttpError, request } from '../../../lib/http'
import type { RevenuePoint } from '../model/revenueSeries'

const EarningsSeries = z.array(
  z.strictObject({ t_ms: z.int(), cum_revenue_cents: z.int().nonnegative() }),
)

export async function fetchEarningsSeries(): Promise<RevenuePoint[]> {
  try {
    return await request('GET', '/api/earnings/series', { schema: EarningsSeries })
  } catch (error) {
    if (error instanceof HttpError && error.status === 409 && error.code === 'no_live_run') {
      return []
    }
    throw error
  }
}

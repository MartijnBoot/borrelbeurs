/**
 * The current run's config document (Phase 6 SD5, PD6): `GET
 * /api/runs/{run_id}/config` for the run `useCurrentRun` finds. It refetches
 * whenever that does -- a go-live, a snapshot, a `config` message -- so a
 * section's `useEditableRecord` sees every server change (AC5).
 *
 * `faultsOf` maps a 422's `faults` to `{field: message}`, by each fault's last
 * `loc` part, so a section shows the server's refusal under its field.
 */
import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { HttpError, request } from '../../lib/http'
import { useCurrentRun } from './useCurrentRun'

export const RunConfig = z.object({
  revision: z.number().int(),
  run: z.object({
    run_id: z.number().int(),
    name: z.string(),
    status: z.enum(['draft', 'live', 'ended']),
    candle_interval_s: z.number().int(),
  }),
  params: z.object({
    step_quant: z.number(),
    eta: z.number(),
    K: z.number(),
    lambda_orders: z.number(),
    alpha_price: z.number(),
    phi_persist: z.number(),
    decay_rho: z.number(),
    history_window_minutes: z.number(),
    refresh_minutes: z.number(),
    idle_decay_minutes: z.number(),
    idle_rise_minutes: z.number(),
    idle_strength: z.number(),
    idle_rise_strength: z.number(),
    idle_targets: z.array(z.number().int()),
    idle_rise_targets: z.array(z.number().int()),
    demand_enabled: z.boolean(),
    auto_calibrate_s0: z.boolean(),
  }),
  drinks: z.array(
    z.object({
      drink_id: z.number().int(),
      slot: z.number().int(),
      name: z.string(),
      active: z.boolean(),
      p_min_cents: z.number().int(),
      p0_cents: z.number().int(),
      p_max_cents: z.number().int(),
      bar_price_cents: z.number().int(),
      a: z.number(),
      d: z.number(),
      s0: z.number(),
      c: z.number(),
    }),
  ),
})
export type RunConfig = z.infer<typeof RunConfig>

export const Revision = z.object({ revision: z.number().int() })

export function useRunConfig() {
  const { run, reload: reloadRun } = useCurrentRun()
  const runId = run?.run_id ?? null
  const [config, setConfig] = useState<RunConfig | null>(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(
    (id: number) =>
      request('GET', `/api/runs/${id}/config`, { schema: RunConfig }).then(
        (document) => {
          setConfig(document)
          setFailed(false)
        },
        () => setFailed(true),
      ),
    [],
  )

  useEffect(() => {
    if (runId !== null) void load(runId)
  }, [load, runId, run])

  const reload = useCallback(async () => {
    await reloadRun()
    if (runId !== null) await load(runId)
  }, [load, reloadRun, runId])

  return { run, config, failed, reload }
}

const Faults = z.array(
  z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() }),
)

/** A 422's faults as `{field: message}`; empty for any other failure. */
export function faultsOf(error: unknown): Record<string, string> {
  if (!(error instanceof HttpError) || error.status !== 422) return {}
  const faults = Faults.safeParse(error.details.faults)
  if (!faults.success) return {}
  const byField: Record<string, string> = {}
  for (const fault of faults.data) {
    const field = fault.loc.at(-1)
    if (typeof field === 'string') byField[field] = fault.msg
  }
  return byField
}

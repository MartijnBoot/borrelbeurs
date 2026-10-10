/**
 * A run's exports (Phase 7 SD6, SD12; PD8): list, one, request. The file
 * itself is a plain link to `/api/exports/{id}/file`, sent with the session
 * cookie like any same-origin request.
 */
import { z } from 'zod'
import { request } from '../../../lib/http'

export const ExportData = z.object({
  export_id: z.number().int(),
  run_id: z.number().int(),
  kind: z.enum(['manual', 'final']),
  status: z.enum(['queued', 'running', 'done', 'failed']),
  requested_by: z.string(),
  sha256: z.string().nullable(),
  bytes: z.number().int().nullable(),
  line_count: z.number().int().nullable(),
  total_cents: z.number().int().nullable(),
  error: z.string().nullable(),
  created_at_ms: z.number().int(),
  started_at_ms: z.number().int().nullable(),
  finished_at_ms: z.number().int().nullable(),
})
export type ExportData = z.infer<typeof ExportData>

export function listExports(runId: number): Promise<ExportData[]> {
  return request('GET', `/api/runs/${runId}/exports`, { schema: z.array(ExportData) })
}

export function getExport(exportId: number): Promise<ExportData> {
  return request('GET', `/api/exports/${exportId}`, { schema: ExportData })
}

/** 202 with the export -- the run's own in-flight one if it has one -- or 409 `export_busy`. */
export function requestExport(runId: number): Promise<ExportData> {
  return request('POST', `/api/runs/${runId}/exports`, { schema: ExportData })
}

export const fileUrl = (exportId: number) => `/api/exports/${exportId}/file`

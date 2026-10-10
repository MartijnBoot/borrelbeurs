/**
 * A run's exports (Phase 7 SD6, SD12): request, poll, download. A stub until
 * T21 fills it; its props are final.
 */
export interface ExportPanelProps {
  runId: number
}

export function ExportPanel({ runId }: ExportPanelProps) {
  void runId // filled in by T21
  return null
}

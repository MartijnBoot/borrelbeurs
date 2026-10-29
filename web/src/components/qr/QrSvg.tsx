/**
 * A QR module matrix drawn as one SVG `<rect>` per dark module, never as markup
 * from the library (`htmlSinks`). Shared by the player's wallet code (B-05 SD14)
 * and the sign-up code (B-09 SD5), so the two cannot drift. The caller sizes it
 * and keeps it black on white whatever the theme.
 */
import type { Modules } from './qrFiles'

export function QrSvg({
  modules,
  label,
  className,
}: {
  modules: Modules
  label: string
  className?: string
}) {
  const size = modules.length
  return (
    <svg
      role="img"
      aria-label={label}
      className={className}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
    >
      {modules.flatMap((row, y) =>
        row.map((dark, x) =>
          dark ? <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill="#000" /> : null,
        ),
      )}
    </svg>
  )
}

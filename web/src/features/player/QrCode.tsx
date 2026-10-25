/**
 * The wallet's QR code (B-05 SD14, AC9): the token encoded by `uqr` (approved at
 * T12) and drawn here as one SVG `<rect>` per dark module, never as markup
 * from the library (`htmlSinks`). Black on white whatever the theme, so every
 * scanner reads it; 240 CSS px, above the 200 a phone camera needs.
 */
import { memo, useMemo } from 'react'
import { encode } from 'uqr'
import styles from './PlayerPage.module.css'

export const QrCode = memo(function QrCode({ token }: { token: string }) {
  const modules = useMemo(() => encode(token, { ecc: 'M', border: 2 }).data, [token])
  const size = modules.length
  return (
    <svg
      role="img"
      aria-label="QR-code"
      className={styles.qr}
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
})

/**
 * The wallet's QR code (B-05 SD14, AC9): the token encoded by `uqr` (approved at
 * T12) and drawn by the shared `QrSvg`. Black on white whatever the theme, so
 * every scanner reads it; 240 CSS px, above the 200 a phone camera needs.
 */
import { memo, useMemo } from 'react'
import { encode } from 'uqr'
import { QrSvg } from '../../components/qr/QrSvg'
import styles from './PlayerPage.module.css'

export const QrCode = memo(function QrCode({ token }: { token: string }) {
  const modules = useMemo(() => encode(token, { ecc: 'M', border: 2 }).data, [token])
  return <QrSvg modules={modules} label="QR-code" className={styles.qr} />
})

/**
 * The koers screen's sign-up block (B-10 SD7, SD10): a white card with the
 * sign-up QR code over "Meld je aan", at the left of the marquees' band. The
 * matrix is drawn from the link alone (`signupBlockLink`), so a new `signup`
 * message redraws it and no older code can show after it (SD8).
 */
import { useMemo } from 'react'
import { encode } from 'uqr'
import { QrSvg } from '../../components/qr/QrSvg'
import { SIGNUP_QR } from '../../components/qr/signupLink'
import styles from './SignupBlock.module.css'

export function SignupBlock({ link }: { link: string }) {
  const modules = useMemo(() => encode(link, SIGNUP_QR).data, [link])
  return (
    <div className={styles.card}>
      <QrSvg modules={modules} label="Aanmeld-QR-code" className={styles.qr} />
      <span className={styles.caption}>Meld je aan</span>
    </div>
  )
}

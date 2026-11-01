/**
 * The sign-up QR code's inputs (B-09): the link it encodes (SD1), its error
 * correction and quiet zone (SD3), the downloaded file's name (SD8) and
 * whether the page is open at a loopback address, where a printed link would
 * point at the phone itself (SD2). All but the file name live in
 * `components/qr/signupLink.ts`, shared with the koers screen (B-10 PD6).
 */
export { isLoopbackHost, pageAddress, SIGNUP_QR, signupLink } from '../../components/qr/signupLink'

/** `aanmelden-<host>-<code>.<ext>`, one `-` per character outside `[A-Za-z0-9.-]` (SD8). */
export function signupFileName(host: string, code: string, ext: 'png' | 'svg'): string {
  const safe = (text: string) => text.replace(/[^A-Za-z0-9.-]/gu, '-')
  return `aanmelden-${safe(host)}-${safe(code)}.${ext}`
}

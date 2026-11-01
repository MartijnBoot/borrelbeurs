/**
 * The koers screen's sign-up rule (B-10 SD2, SD6; PD7): the link its QR code
 * encodes, or `null` for no block. The block shows only with the switch on, a
 * code set and an address known. The address is the server's `public_url` when
 * set, whatever page the screen is open at, else the page's own origin -- unless
 * that is a loopback host, where the link would send every phone to itself.
 */
import { isLoopbackHost, signupLink } from '../../components/qr/signupLink'
import type { SignupData } from '../exchange'

export function signupBlockLink(
  signup: SignupData | null,
  origin: string,
  hostname: string,
): string | null {
  if (!signup?.show_on_screen || !signup.signup_code?.trim()) return null
  const base = signup.public_url ?? (isLoopbackHost(hostname) ? null : origin)
  return base === null ? null : signupLink(base, signup.signup_code)
}

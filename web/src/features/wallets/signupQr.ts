/**
 * The sign-up QR code's inputs (B-09): the link it encodes (SD1), its error
 * correction and quiet zone (SD3), the downloaded file's name (SD8) and
 * whether the page is open at a loopback address, where a printed link would
 * point at the phone itself (SD2).
 */

/** `Q` survives about 25% damage; 4 modules is the standard quiet zone (SD3). */
export const SIGNUP_QR = { ecc: 'Q', border: 4 } as const

export function signupLink(origin: string, code: string): string {
  return `${origin}/speler?code=${encodeURIComponent(code)}`
}

/** `aanmelden-<host>-<code>.<ext>`, one `-` per character outside `[A-Za-z0-9.-]` (SD8). */
export function signupFileName(host: string, code: string, ext: 'png' | 'svg'): string {
  const safe = (text: string) => text.replace(/[^A-Za-z0-9.-]/gu, '-')
  return `aanmelden-${safe(host)}-${safe(code)}.${ext}`
}

/** `URL.hostname` keeps an IPv6 host's brackets, so `[::1]` is the string to match. */
export function isLoopbackHost(hostname: string): boolean {
  return (
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/u.test(hostname) ||
    hostname === '[::1]'
  )
}

/** Where the page is open; one function so a test can stand in for jsdom's localhost (PD8). */
export function pageAddress(): { origin: string; host: string; hostname: string } {
  const { origin, host, hostname } = window.location
  return { origin, host, hostname }
}

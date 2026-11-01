/**
 * The sign-up QR code's link and its drawing (B-09 SD1, SD3), shared by the
 * Wallets preview and the koers screen's block (B-10 PD6), and whether the page
 * is open at a loopback address, where a link built from it would point at the
 * phone itself (B-09 SD2).
 */

/** `Q` survives about 25% damage; 4 modules is the standard quiet zone (SD3). */
export const SIGNUP_QR = { ecc: 'Q', border: 4 } as const

export function signupLink(origin: string, code: string): string {
  return `${origin}/speler?code=${encodeURIComponent(code)}`
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

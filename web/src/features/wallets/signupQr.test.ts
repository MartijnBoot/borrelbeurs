// The sign-up QR code's link, filename and loopback test (B-09 SD1, SD2, SD8; AC8, AC10).
import { describe, expect, it } from 'vitest'
import { isLoopbackHost, signupFileName, signupLink } from './signupQr'

describe('signupLink (SD1)', () => {
  it('escapes the code as a query value', () => {
    expect(signupLink('http://192.168.8.10', 'a b&c#é')).toBe(
      'http://192.168.8.10/speler?code=a%20b%26c%23%C3%A9',
    )
  })
})

describe('signupFileName (SD8, AC8)', () => {
  it.each([
    ['192.168.8.10', 'BORREL', 'png', 'aanmelden-192.168.8.10-BORREL.png'],
    ['signup.test:4173', 'Borrel 2026!', 'svg', 'aanmelden-signup.test-4173-Borrel-2026-.svg'],
    ['192.168.8.10', 'café', 'png', 'aanmelden-192.168.8.10-caf-.png'],
    // An astral character is two UTF-16 halves, and still one dash. Written as an
    // escape, so this file passes `noEmoji.test.ts` (B-02 SD12).
    ['192.168.8.10', 'bier\u{1F37A}', 'png', 'aanmelden-192.168.8.10-bier-.png'],
  ] as const)('%s and %j give %s', (host, code, ext, name) => {
    expect(signupFileName(host, code, ext)).toBe(name)
  })
})

describe('isLoopbackHost (SD2, AC10)', () => {
  it.each(['localhost', 'app.localhost', '127.0.0.1', '127.255.0.9', '[::1]'])(
    '%s is loopback',
    (hostname) => expect(isLoopbackHost(hostname)).toBe(true),
  )

  it.each(['192.168.8.10', 'localhost.example', '128.0.0.1', 'borrelbeurs.onrender.com', '[::2]'])(
    '%s is not',
    (hostname) => expect(isLoopbackHost(hostname)).toBe(false),
  )
})

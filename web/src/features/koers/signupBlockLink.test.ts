// The koers screen's sign-up rule (B-10 SD2, SD6; AC2, AC3, AC13; PD7), as a table.
import { describe, expect, it } from 'vitest'
import type { SignupData } from '../exchange'
import { signupBlockLink } from './signupBlockLink'

const LAN = 'http://192.168.8.10'

// Each page the koers screen may be open at, and the base its link uses with and
// without a `public_url`: `public_url` wins everywhere (AC2); without one a
// loopback page has no usable address (AC3).
const PAGES: { page: string; withUrl: string; withoutUrl: string | null }[] = [
  { page: 'http://localhost', withUrl: LAN, withoutUrl: null },
  { page: 'http://127.0.0.1:4173', withUrl: LAN, withoutUrl: null },
  { page: 'http://[::1]', withUrl: LAN, withoutUrl: null },
  { page: 'http://signup.test:4173', withUrl: LAN, withoutUrl: 'http://signup.test:4173' },
  {
    page: 'https://borrelbeurs.onrender.com',
    withUrl: LAN,
    withoutUrl: 'https://borrelbeurs.onrender.com',
  },
]

// The switch and the code: the block shows only for the switch on and a real code.
const STATES: { show: boolean; code: string | null; shown: boolean }[] = [
  { show: false, code: null, shown: false },
  { show: false, code: '', shown: false },
  { show: false, code: '  ', shown: false },
  { show: false, code: 'BORREL', shown: false },
  { show: true, code: null, shown: false },
  { show: true, code: '', shown: false },
  { show: true, code: '  ', shown: false },
  { show: true, code: 'BORREL', shown: true },
]

function linkAt(signup: SignupData | null, page: string): string | null {
  const { origin, hostname } = new URL(page)
  return signupBlockLink(signup, origin, hostname)
}

const cases = STATES.flatMap(({ show, code, shown }) =>
  PAGES.flatMap(({ page, withUrl, withoutUrl }) =>
    [
      { publicUrl: null, base: withoutUrl },
      { publicUrl: LAN, base: withUrl },
    ].map(({ publicUrl, base }) => ({
      show,
      code,
      publicUrl,
      page,
      expected: shown && base !== null ? `${base}/speler?code=BORREL` : null,
    })),
  ),
)

describe('signupBlockLink', () => {
  it('covers the whole cross: 2 switches × 4 codes × 2 addresses × 5 pages', () => {
    expect(cases).toHaveLength(80)
  })

  it.each(cases)(
    'show=$show code=$code public_url=$publicUrl at $page is $expected',
    ({ show, code, publicUrl, page, expected }) => {
      const signup = { show_on_screen: show, signup_code: code, public_url: publicUrl }
      expect(linkAt(signup, page)).toBe(expected)
    },
  )

  it('public_url wins at localhost (AC2)', () => {
    const signup = { show_on_screen: true, signup_code: 'BORREL', public_url: LAN }
    expect(linkAt(signup, 'http://localhost')).toBe('http://192.168.8.10/speler?code=BORREL')
  })

  it('no public_url at a loopback host is no block (AC3)', () => {
    const signup = { show_on_screen: true, signup_code: 'BORREL', public_url: null }
    for (const page of ['http://localhost', 'http://app.localhost', 'http://127.0.0.2'])
      expect(linkAt(signup, page)).toBeNull()
  })

  it('no signup state yet is no block', () => {
    expect(linkAt(null, 'https://borrelbeurs.onrender.com')).toBeNull()
  })

  it('encodes an awkward code as the link of AC2', () => {
    const signup = { show_on_screen: true, signup_code: 'a b&c#é', public_url: LAN }
    expect(linkAt(signup, 'http://localhost')).toBe(
      `${LAN}/speler?code=${encodeURIComponent('a b&c#é')}`,
    )
    expect(linkAt(signup, 'http://localhost')).toBe(`${LAN}/speler?code=a%20b%26c%23%C3%A9`)
  })
})

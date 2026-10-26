// AC20's source scan (B-05 T17, SD24): no wallet page calls `crypto.randomUUID`.
// B-06 (SD12, AC31, D-49) adds the bar, which pays from a wallet and is served
// over plain HTTP at the venue just as the kassa is.
//
// A browser offers `randomUUID` only in a secure context, and at the venue the
// kassa and bar pages are plain HTTP on a LAN address, where the call throws
// (D-49). Their keys come from `lib/idempotencyKey.ts` instead. The scan reads
// the tree with Vite's `import.meta.glob` as raw text, as
// `features/exchange/model/quote.provenance.test.ts` does, and is run on a
// planted call too, so a scan that cannot fail shows up as a failing test.
import { describe, expect, it } from 'vitest'

const WALLET_CODE: readonly string[] = [
  'src/features/player/',
  'src/features/kassa/',
  'src/features/wallets/',
  'src/features/bar/',
  'src/lib/idempotencyKey.ts',
]
const RANDOM_UUID = /\brandomUUID\b/

interface Source {
  path: string
  text: string
}

function randomUuidCalls(sources: readonly Source[]): string[] {
  const found: string[] = []
  for (const { path, text } of sources) {
    if (!WALLET_CODE.some((prefix) => path.startsWith(prefix))) continue
    // A test may delete it from the global, or hand it to a model as its key source.
    if (path.endsWith('.test.ts') || path.endsWith('.test.tsx')) continue
    text.split('\n').forEach((line, i) => {
      if (RANDOM_UUID.test(line)) found.push(`${path}:${i + 1}`)
    })
  }
  return found
}

const RAW: Record<string, string> = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
})

function tree(): Source[] {
  return Object.entries(RAW).map(([path, text]) => ({ path: path.slice(1), text }))
}

describe('wallet code provenance (AC20, B-06 AC31)', () => {
  it('no wallet or bar code names crypto.randomUUID', () => {
    const sources = tree()
    expect(sources.some((s) => s.path === 'src/lib/idempotencyKey.ts')).toBe(true)
    expect(sources.some((s) => s.path.startsWith('src/features/player/'))).toBe(true)
    expect(sources.some((s) => s.path === 'src/features/bar/useBarController.ts')).toBe(true)
    expect(randomUuidCalls(sources)).toEqual([])
  })

  it('catches a planted call', () => {
    const planted = {
      path: 'src/features/kassa/TopUpPanel.tsx',
      text: 'const key = crypto.randomUUID()\n',
    }
    expect(randomUuidCalls([...tree(), planted])).toEqual(['src/features/kassa/TopUpPanel.tsx:1'])
  })

  it('catches a planted call in the bar', () => {
    const planted = {
      path: 'src/features/bar/useBarController.ts',
      text: 'const key = crypto.randomUUID()\n',
    }
    expect(randomUuidCalls([planted])).toEqual(['src/features/bar/useBarController.ts:1'])
  })

  it('skips test files, .test.tsx included', () => {
    const tests = [
      { path: 'src/features/bar/OrderPad.test.tsx', text: 'crypto.randomUUID()' },
      { path: 'src/features/bar/model/barController.test.ts', text: 'crypto.randomUUID()' },
    ]
    expect(randomUuidCalls(tests)).toEqual([])
  })

  it('leaves code outside the wallet and bar pages alone', () => {
    const elsewhere = { path: 'src/features/koers/KoersPage.tsx', text: 'crypto.randomUUID()' }
    expect(randomUuidCalls([elsewhere])).toEqual([])
  })
})

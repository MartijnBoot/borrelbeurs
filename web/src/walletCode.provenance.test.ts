// AC20's source scan (B-05 T17, SD24): no wallet page calls `crypto.randomUUID`.
//
// A browser offers `randomUUID` only in a secure context, and at the venue the
// kassa page is plain HTTP on a LAN address, where the call throws (D-49). The
// wallet code's keys come from `lib/idempotencyKey.ts` instead. The scan reads
// the tree with Vite's `import.meta.glob` as raw text, as
// `features/exchange/model/quote.provenance.test.ts` does, and is run on a
// planted call too, so a scan that cannot fail shows up as a failing test.
import { describe, expect, it } from 'vitest'

const WALLET_CODE: readonly string[] = [
  'src/features/player/',
  'src/features/kassa/',
  'src/features/wallets/',
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
    if (path.endsWith('.test.ts')) continue // a test may delete it from the global
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

describe('wallet code provenance (AC20)', () => {
  it('no wallet code names crypto.randomUUID', () => {
    const sources = tree()
    expect(sources.some((s) => s.path === 'src/lib/idempotencyKey.ts')).toBe(true)
    expect(sources.some((s) => s.path.startsWith('src/features/player/'))).toBe(true)
    expect(randomUuidCalls(sources)).toEqual([])
  })

  it('catches a planted call', () => {
    const planted = {
      path: 'src/features/kassa/TopUpPanel.tsx',
      text: 'const key = crypto.randomUUID()\n',
    }
    expect(randomUuidCalls([...tree(), planted])).toEqual(['src/features/kassa/TopUpPanel.tsx:1'])
  })

  it('leaves code outside the wallet pages alone', () => {
    const elsewhere = { path: 'src/features/bar/useBarController.ts', text: 'crypto.randomUUID()' }
    expect(randomUuidCalls([elsewhere])).toEqual([])
  })
})

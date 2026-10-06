// AC2's source scan (Phase 5 T4, PD2): a `Quote` is built only by quote.ts,
// and its builders are called only by the reducer and the order intents.
//
// The brand makes a hand-built `Quote` a type error; this scan closes the
// escape hatch the type system leaves open -- a cast. It fails on:
// - `as Quote` or `<Quote>` in any file other than quote.ts (tests included);
// - a call to a `quoteFrom*` builder in any non-test file other than
//   applyMessage.ts (one message -> one quote) and orderIntents.ts (one 409
//   body -> one quote).
// The scanner is run on a planted forgery too, so a scan that cannot fail
// shows up as a failing test.
//
// The tree is read with Vite's `import.meta.glob` as raw text, so the scan
// needs no Node types in the app's tsconfig.
import { describe, expect, it } from 'vitest'

const BUILDER = 'src/features/exchange/model/quote.ts'
// This file: its planted forgeries are strings, not code.
const SELF = 'src/features/exchange/model/quote.provenance.test.ts'
const MAY_BUILD: ReadonlySet<string> = new Set([
  'src/features/exchange/model/applyMessage.ts',
  'src/features/bar/model/orderIntents.ts',
])
const CAST = /\bas\s+Quote\b|<Quote>/
const BUILD_CALL = /\bquoteFrom\w+\s*\(/
const TEST_FILE = /\.test\.tsx?$/

interface Source {
  path: string
  text: string
}

function quoteForgeries(sources: readonly Source[]): string[] {
  const found: string[] = []
  for (const { path, text } of sources) {
    if (path === BUILDER || path === SELF) continue
    text.split('\n').forEach((line, i) => {
      const where = `${path}:${i + 1}`
      if (CAST.test(line)) found.push(`${where}: casts to Quote`)
      if (BUILD_CALL.test(line) && !MAY_BUILD.has(path) && !TEST_FILE.test(path)) {
        found.push(`${where}: calls a Quote builder`)
      }
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

describe('Quote provenance (AC2)', () => {
  it('the source tree builds a Quote only through its builders, called only where allowed', () => {
    const sources = tree()
    expect(sources.some((s) => s.path === BUILDER)).toBe(true) // the walk sees quote.ts
    expect(quoteForgeries(sources)).toEqual([])
  })

  it('catches a planted cast', () => {
    const planted = {
      path: 'src/features/bar/OrderPad.tsx',
      text: 'const q = { version: 1, prices: {}, receivedAt: 0 } as Quote\n',
    }
    expect(quoteForgeries([...tree(), planted])).toEqual([
      'src/features/bar/OrderPad.tsx:1: casts to Quote',
    ])
  })

  it('catches a planted double cast and an angle-bracket cast', () => {
    expect(
      quoteForgeries([
        { path: 'src/a.ts', text: 'const q = x as unknown as Quote' },
        { path: 'src/b.ts', text: 'const q = <Quote>x' },
      ]),
    ).toHaveLength(2)
  })

  it('catches a builder called from anywhere else', () => {
    const planted = {
      path: 'src/features/bar/model/barController.ts',
      text: 'const q = quoteFromTick(lastTick, now)\n',
    }
    expect(quoteForgeries([planted])).toEqual([
      'src/features/bar/model/barController.ts:1: calls a Quote builder',
    ])
  })

  it('lets the reducer and the order intents call the builders', () => {
    expect(
      quoteForgeries([
        { path: 'src/features/exchange/model/applyMessage.ts', text: 'quoteFromTick(m, at)' },
        { path: 'src/features/bar/model/orderIntents.ts', text: 'quoteFromPriceChanged(b, at)' },
      ]),
    ).toEqual([])
  })
})

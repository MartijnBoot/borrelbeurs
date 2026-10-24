// B-02 SD12, AC14: the app draws its own pixel icons, so no file the web app is
// built or tested from may hold an emoji. It fails on any
// `Extended_Pictographic` code point, the variation selector U+FE0F, or one of
// the font-drawn symbols the icons replaced (U+25B2, U+25BC, U+25BE, U+26A0) in
// any file under `src/` or `e2e/`, or in `index.html` -- tests and comments
// included. One failure per hit, as `path:line: U+XXXX`.
//
// Every file is read; one whose extension is neither scanned text nor a named
// binary fails too, so a new file type cannot slip past (PD12). Text a person
// types (news, drink names) is data, not source, and keeps its emoji (SD6).
// The banned characters appear here only as escapes, so this file passes its
// own scan. After `quote.provenance.test.ts`: `path:line` messages, an
// anti-vacuity count and planted strings that show the scan can fail. The tree
// is read from disk, like `lint-rules.test.ts`, because Vitest stubs CSS
// imports -- `?raw` included.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const BANNED = /\p{Extended_Pictographic}|\u{FE0F}|[\u{25B2}\u{25BC}\u{25BE}\u{26A0}]/gu
const TEXT = /\.(ts|tsx|css|json|html)$/
const BINARY = /\.png$/

interface Source {
  path: string
  text: string
}

function emojiHits(sources: readonly Source[]): string[] {
  const found: string[] = []
  for (const { path, text } of sources) {
    text.split('\n').forEach((line, i) => {
      for (const [char] of line.matchAll(BANNED)) {
        const code = char.codePointAt(0)!.toString(16).toUpperCase().padStart(4, '0')
        found.push(`${path}:${i + 1}: U+${code}`)
      }
    })
  }
  return found
}

const WEB = fileURLToPath(new URL('../', import.meta.url))

/** Every file SD12 covers, relative to `web/`, with `/` separators. */
const EVERY: readonly string[] = [
  ...['src', 'e2e'].flatMap((dir) =>
    readdirSync(WEB + dir, { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => `${entry.parentPath}/${entry.name}`.slice(WEB.length).replaceAll('\\', '/')),
  ),
  'index.html',
]

const TREE: readonly Source[] = EVERY.filter((path) => TEXT.test(path)).map((path) => ({
  path,
  text: readFileSync(WEB + path, 'utf-8'),
}))

const tree = (): Source[] => [...TREE]

describe('no emoji in the web app (B-02 SD12, AC14)', () => {
  it('reads every file it is meant to', () => {
    // Anti-vacuity: the 221 files under src/ and e2e/ at B-02 (this one included),
    // plus index.html; every one either scanned or a named binary.
    expect(EVERY.length).toBeGreaterThanOrEqual(222)
    for (const path of ['index.html', 'src/noEmoji.test.ts', 'e2e/icons.spec.ts']) {
      expect(EVERY).toContain(path)
    }
    expect(EVERY.filter((path) => !TEXT.test(path) && !BINARY.test(path))).toEqual([])
    expect(TREE.length).toBe(EVERY.filter((path) => !BINARY.test(path)).length)
    const css = TREE.find((s) => s.path === 'src/styles/keyframes.css')
    expect(css?.text).toContain('.market-banner')
  })

  it('finds none in the source tree', () => {
    expect(emojiHits(tree())).toEqual([])
  })

  it.each([
    ['\u{26A0}', 'U+26A0'],
    ['\u{25B2}', 'U+25B2'],
    ['\u{25BC}', 'U+25BC'],
    ['\u{25BE}', 'U+25BE'],
    ['\u{1F37A}', 'U+1F37A'],
    ['\u{2699}\u{FE0F}', 'U+2699'],
  ])('catches a planted %s', (char, code) => {
    const planted = { path: 'src/features/bar/BarPage.tsx', text: `x\n<h1>${char} Bar</h1>\n` }
    expect(emojiHits([...tree(), planted])[0]).toBe(`src/features/bar/BarPage.tsx:2: ${code}`)
  })

  it('names the variation selector too', () => {
    const planted = { path: 'src/a.ts', text: "const a = '\u{2699}\u{FE0F}'" }
    expect(emojiHits([planted])).toEqual(['src/a.ts:1: U+2699', 'src/a.ts:1: U+FE0F'])
  })

  it('leaves the app’s ordinary symbols alone', () => {
    const text = '\u{20AC} 2,50 \u{2192} 3\u{00D7} \u{2026} \u{2014} (i) \u{00EB}'
    expect(emojiHits([{ path: 'src/a.ts', text }])).toEqual([])
  })
})

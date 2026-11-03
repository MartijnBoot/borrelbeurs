// B-12 SD7, AC19: every on/off in the app is a `Switch` (`role="switch"`), so no
// `.ts`/`.tsx` file under `src/` may make a checkbox -- neither JSX's
// `type="checkbox"` nor an object's `type: 'checkbox'`. One failure per hit,
// `path:line`. This file is the one exception: it has to name what it bans.
// After `noEmoji.test.ts`: the tree is read from disk, and planted strings show
// the scan can fail.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const BANNED = /\btype\s*[=:]\s*\{?\s*["'`]checkbox["'`]/g
const SOURCE = /\.(ts|tsx)$/
const SELF = 'src/noCheckbox.test.ts'

interface Source {
  path: string
  text: string
}

function checkboxHits(sources: readonly Source[]): string[] {
  const found: string[] = []
  for (const { path, text } of sources) {
    text.split('\n').forEach((line, i) => {
      if (line.match(BANNED) !== null) found.push(`${path}:${i + 1}`)
    })
  }
  return found
}

const WEB = fileURLToPath(new URL('../', import.meta.url))

/** Every `.ts`/`.tsx` file under `src/`, relative to `web/`, with `/` separators. */
const EVERY: readonly string[] = readdirSync(WEB + 'src', { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => `${entry.parentPath}/${entry.name}`.slice(WEB.length).replaceAll('\\', '/'))
  .filter((path) => SOURCE.test(path))

const tree = (): Source[] =>
  EVERY.filter((path) => path !== SELF).map((path) => ({
    path,
    text: readFileSync(WEB + path, 'utf-8'),
  }))

describe('no checkbox in the web app (B-12 SD7, AC19)', () => {
  it('reads every source file', () => {
    // Anti-vacuity: 248 .ts/.tsx files under src/ at B-12 T4.
    expect(EVERY.length).toBeGreaterThanOrEqual(240)
    for (const path of [SELF, 'src/components/ui/Switch.tsx', 'src/main.tsx']) {
      expect(EVERY).toContain(path)
    }
  })

  it('finds none in the source tree', () => {
    expect(checkboxHits(tree())).toEqual([])
  })

  it.each([
    ['JSX', '<input\n  type="checkbox"\n/>', 'src/a.tsx:2'],
    ['JSX in braces', "<input type={'checkbox'} />", 'src/a.tsx:1'],
    ['an object', "const props = { type: 'checkbox' }", 'src/a.tsx:1'],
  ])('catches a planted checkbox (%s)', (_kind, text, hit) => {
    expect(checkboxHits([...tree(), { path: 'src/a.tsx', text }])).toEqual([hit])
  })

  it('leaves a switch and other input types alone', () => {
    const text = '<button role="switch" />\n<input type="text" />\nconst kind = "checkbox"'
    expect(checkboxHits([{ path: 'src/a.tsx', text }])).toEqual([])
  })
})

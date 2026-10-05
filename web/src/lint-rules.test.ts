// Self-tests for the lint rules that carry invariants (SD27, PD9): each rule
// gets one violating and one clean snippet, linted with the real
// eslint.config.js. boundaries only checks imports it can resolve, so the
// snippets are linted inside a scratch tree under the OS temp dir that holds
// real feature entry points -- nothing is written into src/.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { ESLint } from 'eslint'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

let root: string
let eslint: ESLint

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'bb-lint-rules-'))
  for (const feature of ['exchange', 'koers', 'theme']) {
    mkdirSync(join(root, 'src/features', feature), { recursive: true })
    writeFileSync(join(root, 'src/features', feature, 'index.ts'), 'export const x = 1\n')
  }
  mkdirSync(join(root, 'src/lib'), { recursive: true })
  writeFileSync(join(root, 'src/lib/format.ts'), 'export const x = 1\n')
  eslint = new ESLint({ cwd: root, overrideConfigFile: resolve('eslint.config.js') })
})

afterAll(() => {
  rmSync(root, { recursive: true, force: true })
})

async function ruleIds(code: string, filePath: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: join(root, filePath) })
  return result.messages.map((m) => m.ruleId ?? `fatal: ${m.message}`)
}

const importX = (from: string) => `import { x } from '${from}'\nexport const y = x\n`

describe('feature boundaries', () => {
  it('forbids exchange from importing any other feature', async () => {
    expect(await ruleIds(importX('../koers'), 'src/features/exchange/a.ts')).toContain(
      'boundaries/dependencies',
    )
  })

  it('lets exchange import lib', async () => {
    expect(await ruleIds(importX('../../lib/format'), 'src/features/exchange/a.ts')).not.toContain(
      'boundaries/dependencies',
    )
  })

  it('forbids a feature from importing a sibling other than exchange', async () => {
    expect(await ruleIds(importX('../koers'), 'src/features/theme/a.ts')).toContain(
      'boundaries/dependencies',
    )
  })

  it('lets a feature import exchange', async () => {
    expect(await ruleIds(importX('../exchange'), 'src/features/theme/a.ts')).toEqual([])
  })

  it('lets the app layer import any feature', async () => {
    expect(await ruleIds(importX('../features/koers'), 'src/app/a.ts')).toEqual([])
  })
})

describe('HTML sinks', () => {
  it('forbids dangerouslySetInnerHTML', async () => {
    const code = 'export const A = (h: string) => <div dangerouslySetInnerHTML={{ __html: h }} />\n'
    expect(await ruleIds(code, 'src/features/koers/A.tsx')).toContain('no-restricted-syntax')
  })

  it('allows ordinary JSX attributes', async () => {
    const code = 'export const A = (t: string) => <div title={t}>{t}</div>\n'
    expect(await ruleIds(code, 'src/features/koers/A.tsx')).toEqual([])
  })

  it.each([
    ['innerHTML', 'el.innerHTML = h'],
    ['outerHTML', 'el.outerHTML = h'],
    ['insertAdjacentHTML', "el.insertAdjacentHTML('beforeend', h)"],
  ])('forbids %s', async (_name, statement) => {
    const code = `export function f(el: HTMLElement, h: string) {\n  ${statement}\n}\n`
    expect(await ruleIds(code, 'src/features/koers/a.ts')).toContain('no-restricted-syntax')
  })

  it('allows textContent', async () => {
    const code = 'export function f(el: HTMLElement, h: string) {\n  el.textContent = h\n}\n'
    expect(await ruleIds(code, 'src/features/koers/a.ts')).toEqual([])
  })

  it('still forbids sinks in src/lib/config.ts, where import.meta.env is allowed', async () => {
    const code = 'export function f(el: HTMLElement, h: string) {\n  el.innerHTML = h\n}\n'
    expect(await ruleIds(code, 'src/lib/config.ts')).toContain('no-restricted-syntax')
    expect(await ruleIds('export const e = import.meta.env\n', 'src/lib/config.ts')).toEqual([])
  })
})

describe('web storage', () => {
  it.each([
    ['localStorage', "localStorage.getItem('k')"],
    ['sessionStorage', "sessionStorage.setItem('k', 'v')"],
    ['window.localStorage', "window.localStorage.getItem('k')"],
    ['window.sessionStorage', 'window.sessionStorage.clear()'],
  ])('forbids %s', async (_name, statement) => {
    const ids = await ruleIds(
      `export function f() {\n  ${statement}\n}\n`,
      'src/features/theme/a.ts',
    )
    expect(
      ids.some((id) => id === 'no-restricted-globals' || id === 'no-restricted-properties'),
    ).toBe(true)
  })

  it('allows an in-memory store', async () => {
    const code = "export function f() {\n  return new Map<string, string>().get('k')\n}\n"
    expect(await ruleIds(code, 'src/features/theme/a.ts')).toEqual([])
  })
})

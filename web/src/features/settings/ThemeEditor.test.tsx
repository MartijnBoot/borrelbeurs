// @vitest-environment jsdom
// The custom theme editor (Phase 6 T30: SD28; AC29, AC30 UI). The token list is
// derived from the server's manifest, read here from `app/runtime/theme.py`, so a
// token added there fails this test until the editor shows it (AC29).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ThemeData } from '../exchange'
import { ThemeEditor } from './ThemeEditor'
// The server's own manifest, as text: Vite's `?raw` import, test-only.
import themePy from '../../../../app/runtime/theme.py?raw'

function manifestTokenNames(source: string = themePy): string[] {
  const tuple = /TOKEN_NAMES[^=]*=\s*\(([^)]*)\)/.exec(source)
  if (tuple === null) throw new Error('TOKEN_NAMES not found in app/runtime/theme.py')
  return [...tuple[1].matchAll(/"(--[a-z0-9-]+)"/g)].map((m) => m[1])
}

const TOKEN_NAMES = manifestTokenNames()

const held: ThemeData = {
  preset: 'blauw',
  revision: 3,
  tokens: Object.fromEntries(
    TOKEN_NAMES.map((name, i) => [name, `#${(0x101010 + i).toString(16)}`]),
  ),
  font_family: 'Inter, system-ui, sans-serif',
  images: { bg: null, header: null, logo: null, promo: null },
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  exchangeStore.setState({ ...exchangeStore.getInitialState(), theme: held }, true)
  fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ ...held, preset: 'custom', revision: 4 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(<ThemeEditor />)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const save = () => screen.getByRole('button', { name: 'Opslaan' }) as HTMLButtonElement

describe('ThemeEditor', () => {
  it('the manifest has the 24 tokens this test expects to find', () => {
    expect(TOKEN_NAMES).toHaveLength(24)
  })

  it('has a row per manifest token, a colour and a hex field each (AC29)', () => {
    for (const name of TOKEN_NAMES) {
      const hex = screen.getByLabelText(name) as HTMLInputElement
      expect(hex.value).toBe(held.tokens[name])
      expect(screen.getByLabelText(`${name} kleur`)).toBeTruthy()
    }
  })

  it('a colour pick writes the hex field', () => {
    fireEvent.change(screen.getByLabelText('--bg kleur'), { target: { value: '#abcdef' } })
    expect((screen.getByLabelText('--bg') as HTMLInputElement).value).toBe('#abcdef')
  })

  it('an invalid hex disables save', () => {
    expect(save().disabled).toBe(false)
    fireEvent.change(screen.getByLabelText('--accent'), { target: { value: 'red' } })
    expect(save().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('--accent'), { target: { value: '#12345' } })
    expect(save().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('--accent'), { target: { value: '#fff' } })
    expect(save().disabled).toBe(false)
  })

  it('save sends preset custom, all 24 tokens and the font (AC30, PD8)', async () => {
    fireEvent.change(screen.getByLabelText('--bg'), { target: { value: '#000000' } })
    fireEvent.change(screen.getByLabelText('Lettertype'), { target: { value: 'garamond' } })
    fireEvent.click(save())
    await act(async () => {})

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect([path, init.method]).toEqual(['/api/theme', 'PUT'])
    const body = JSON.parse(String(init.body))
    expect(body.preset).toBe('custom')
    expect(body.font).toBe('garamond')
    expect(Object.keys(body.tokens).sort()).toEqual([...TOKEN_NAMES].sort())
    expect(body.tokens['--bg']).toBe('#000000')
  })

  it('starts from the active theme, Garamond read from its font stack', () => {
    cleanup()
    exchangeStore.setState({
      theme: { ...held, preset: 'oudgeld', font_family: "'EB Garamond', Georgia, serif" },
    })
    render(<ThemeEditor />)
    expect((screen.getByLabelText('Lettertype') as HTMLSelectElement).value).toBe('garamond')
  })
})

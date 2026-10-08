// @vitest-environment jsdom
// 🖼️ Afbeeldingen (Phase 6 T31: SD29; AC31, AC33, AC34, AC39): four slots, each with
// a preview from the store's theme, an upload and a confirmed removal.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore, type ThemeData } from '../exchange'
import { ImagesSection } from './ImagesSection'

const THEME: ThemeData = {
  preset: 'blauw',
  revision: 3,
  tokens: {},
  font_family: 'Inter, system-ui, sans-serif',
  images: { bg: null, header: null, logo: '/assets/7', promo: null },
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let answer: () => Response
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  exchangeStore.setState({ ...exchangeStore.getInitialState(), theme: THEME }, true)
  answer = () => json(201, { asset_id: 8, revision: 4 })
  fetchMock = vi.fn(() => Promise.resolve(answer()))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const slot = (label: string) => screen.getByRole('group', { name: label })
const calls = () => fetchMock.mock.calls as [string, RequestInit][]

function choose(label: string, file: File) {
  fireEvent.change(within(slot(label)).getByLabelText(`${label} kiezen`), {
    target: { files: [file] },
  })
}

describe('ImagesSection', () => {
  it('shows the four slots, with a preview of each set one', () => {
    render(<ImagesSection />)
    for (const label of ['Achtergrond', 'Header', 'Logo', 'Promotie tegel']) {
      expect(slot(label)).toBeTruthy()
    }
    expect(within(slot('Logo')).getByRole('img').getAttribute('src')).toBe('/assets/7')
    expect(within(slot('Achtergrond')).queryByRole('img')).toBeNull()
  })

  it("choosing a file posts its bytes to the slot's URL as multipart `file`", async () => {
    render(<ImagesSection />)
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'promo.png', {
      type: 'image/png',
    })
    choose('Promotie tegel', file)
    await act(async () => {})

    expect(calls()).toHaveLength(1)
    const [path, init] = calls()[0]
    expect([path, init.method]).toEqual(['/api/theme/images/promo', 'POST'])
    expect((init.body as FormData).get('file')).toBe(file)
  })

  it('Cancel on remove sends nothing; Confirm sends DELETE (AC39)', async () => {
    render(<ImagesSection />)
    fireEvent.click(within(slot('Logo')).getByRole('button', { name: 'Verwijderen' }))
    expect(screen.getByRole('dialog', { name: "'Logo' verwijderen?" })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(calls()).toEqual([])

    fireEvent.click(within(slot('Logo')).getByRole('button', { name: 'Verwijderen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await act(async () => {})
    expect(calls().map(([path, init]) => [path, init.method])).toEqual([
      ['/api/theme/images/logo', 'DELETE'],
    ])
  })

  it('an empty slot offers no removal', () => {
    render(<ImagesSection />)
    expect(within(slot('Header')).queryByRole('button', { name: 'Verwijderen' })).toBeNull()
  })

  it('the 415 message is shown in Dutch (AC31)', async () => {
    answer = () => json(415, { error: { code: 'unsupported_media_type', message: 'only PNG...' } })
    render(<ImagesSection />)
    choose('Logo', new File(['<svg/>'], 'logo.png', { type: 'image/png' }))
    await act(async () => {})

    expect(within(slot('Logo')).getByRole('alert').textContent).toBe(
      'Alleen PNG, JPEG, WebP of GIF.',
    )
  })

  it('the 413 message is shown in Dutch (AC33)', async () => {
    answer = () => json(413, { error: { code: 'too_large', message: 'too large' } })
    render(<ImagesSection />)
    choose('Achtergrond', new File(['x'], 'bg.png', { type: 'image/png' }))
    await act(async () => {})

    expect(within(slot('Achtergrond')).getByRole('alert').textContent).toBe(
      'Afbeelding is groter dan 5 MB.',
    )
  })
})

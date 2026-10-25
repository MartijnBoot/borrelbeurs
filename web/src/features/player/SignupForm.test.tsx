// @vitest-environment jsdom
// Sign-up (B-05 SD3, SD6; AC2-AC4, AC6, AC7; PD14, PD15).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SignupForm } from './SignupForm'

const WALLET = {
  name: 'Jan',
  balance_cents: 0,
  qr_token: 'tok-1',
  short_code: 'K7Q4-M2XD',
  created_at: '2026-10-25T10:00:00Z',
}

const json = (status: number, body?: unknown, headers: Record<string, string> = {}) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
const failure = (status: number, code: string, extra: object = {}, headers = {}) =>
  json(status, { error: { code, message: code, ...extra } }, headers)

let answer: (path: string, body: { name: string; code: string }) => Response

beforeEach(() => {
  answer = () => json(201, WALLET)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => answer(path, JSON.parse(String(init?.body)))),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const calls = () =>
  vi.mocked(fetch).mock.calls.map(([path, init]) => [path, JSON.parse(String(init?.body))])

async function show(url = '/speler', onSignedUp = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <SignupForm onSignedUp={onSignedUp} />
    </MemoryRouter>,
  )
  return onSignedUp
}

const nameField = () => screen.getByLabelText('Naam') as HTMLInputElement
const codeField = () => screen.getByLabelText('Aanmeldcode') as HTMLInputElement

async function type(field: HTMLInputElement, value: string) {
  fireEvent.change(field, { target: { value } })
}

async function blur(field: HTMLInputElement) {
  fireEvent.blur(field)
  await act(async () => {})
}

async function submit() {
  fireEvent.click(screen.getByRole('button', { name: 'Aanmelden' }))
  await act(async () => {})
}

describe('the code from the link (AC2)', () => {
  it('fills the code from ?code=', async () => {
    await show('/speler?code=abc')
    expect(codeField().value).toBe('abc')
  })

  it('is empty without it', async () => {
    await show()
    expect(codeField().value).toBe('')
    expect(nameField().maxLength).toBe(40)
  })
})

describe('signing up (AC3)', () => {
  it('a 201 hands the wallet on', async () => {
    const onSignedUp = await show('/speler?code=abc')
    await type(nameField(), 'Jan')
    await submit()
    expect(calls()).toEqual([['/api/wallet', { name: 'Jan', code: 'abc' }]])
    expect(onSignedUp).toHaveBeenCalledWith(WALLET)
  })

  it('a blank name asks nothing and says why', async () => {
    await show('/speler?code=abc')
    await type(nameField(), '   ')
    await submit()
    expect(calls()).toEqual([])
    expect(screen.getByRole('alert').textContent).toBe('Kies een naam van 1 tot 40 tekens.')
  })
})

describe('the name check (AC4, PD14)', () => {
  it('runs once on blur per distinct name and code, never while typing', async () => {
    answer = () => json(200, { available: true, suggestions: [] })
    await show('/speler?code=abc')
    await type(nameField(), 'J')
    await type(nameField(), 'Jan')
    expect(calls()).toEqual([])
    await blur(nameField())
    await blur(nameField())
    await blur(codeField())
    expect(calls()).toEqual([['/api/wallet/name-check', { name: 'Jan', code: 'abc' }]])
    await type(nameField(), 'Piet')
    await blur(nameField())
    expect(calls()).toHaveLength(2)
  })

  it('waits until both fields are filled', async () => {
    await show()
    await type(nameField(), 'Jan')
    await blur(nameField())
    expect(calls()).toEqual([])
  })

  it('a taken name offers three suggestions, and a click signs up with one', async () => {
    answer = (path) =>
      path === '/api/wallet/name-check'
        ? json(200, { available: false, suggestions: ['Jan 2', 'Jan 3', 'Jan 4'] })
        : json(201, { ...WALLET, name: 'Jan 3' })
    const onSignedUp = await show('/speler?code=abc')
    await type(nameField(), 'Jan')
    await blur(nameField())

    expect(screen.getByText('Die naam is al bezet. Kies een andere:')).toBeTruthy()
    const offered = screen.getAllByRole('button').filter((b) => b.textContent?.startsWith('Jan'))
    expect(offered.map((b) => b.textContent)).toEqual(['Jan 2', 'Jan 3', 'Jan 4'])

    fireEvent.click(screen.getByRole('button', { name: 'Jan 3' }))
    await act(async () => {})
    expect(calls().at(-1)).toEqual(['/api/wallet', { name: 'Jan 3', code: 'abc' }])
    expect(nameField().value).toBe('Jan 3')
    expect(onSignedUp).toHaveBeenCalledWith({ ...WALLET, name: 'Jan 3' })
  })

  it('a 409 name_taken on submit offers the same suggestions', async () => {
    answer = () => failure(409, 'name_taken', { suggestions: ['jan 2', 'jan 3', 'jan 4'] })
    const onSignedUp = await show('/speler?code=abc')
    await type(nameField(), 'jan')
    await submit()
    expect(screen.getByRole('button', { name: 'jan 2' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(onSignedUp).not.toHaveBeenCalled()
  })
})

describe('refusals (AC6, AC7, PD15)', () => {
  it.each([
    [failure(403, 'signup_code_invalid'), 'Onjuiste aanmeldcode.'],
    [failure(409, 'signup_closed'), 'Aanmelden is nu gesloten.'],
    [failure(422, 'validation_error'), 'Kies een naam van 1 tot 40 tekens.'],
    [
      failure(429, 'rate_limited', {}, { 'Retry-After': '37' }),
      'Te veel pogingen. Probeer het over 37 seconden opnieuw.',
    ],
  ])('%#: the text for the refusal', async (response, text) => {
    answer = () => response
    const onSignedUp = await show('/speler?code=abc')
    await type(nameField(), 'Jan')
    await submit()
    expect(screen.getByRole('alert').textContent).toBe(text)
    expect(onSignedUp).not.toHaveBeenCalled()
  })

  it('the name check shows the same texts', async () => {
    answer = () => failure(403, 'signup_code_invalid')
    await show('/speler?code=fout')
    await type(nameField(), 'Jan')
    await blur(nameField())
    expect(screen.getByRole('alert').textContent).toBe('Onjuiste aanmeldcode.')
  })

  it('a network failure says so', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    await show('/speler?code=abc')
    await type(nameField(), 'Jan')
    await submit()
    expect(screen.getByRole('alert').textContent).toBe('Verbindingsfout. Probeer opnieuw.')
  })
})

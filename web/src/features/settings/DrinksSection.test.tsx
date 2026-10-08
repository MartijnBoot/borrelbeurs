// @vitest-environment jsdom
// 🥤 Drankjes beheren (Phase 6 T26: SD13, SD25; AC4, AC17, AC21, AC39): add with
// blank optionals omitted, rename and bar price dirty-only, remove behind a dialog.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exchangeStore } from '../exchange'
import { DrinksSection } from './DrinksSection'

const DRINK = {
  slot: 0,
  active: true,
  p_min_cents: 150,
  p0_cents: 260,
  p_max_cents: 500,
  bar_price_cents: 260,
  a: 10,
  d: 0.6,
  s0: 8,
  c: 0.4,
}

const CONFIG = {
  revision: 3,
  run: { run_id: 7, name: 'Vrijmibo', status: 'live', candle_interval_s: 60 },
  params: {
    step_quant: 0.1,
    eta: 0.6,
    K: 12,
    lambda_orders: 0.8,
    alpha_price: 0,
    phi_persist: 0.03,
    decay_rho: 0.98,
    history_window_minutes: 15,
    refresh_minutes: 1,
    idle_decay_minutes: 1,
    idle_rise_minutes: 1,
    idle_strength: 0.5,
    idle_rise_strength: 0.5,
    idle_targets: [],
    idle_rise_targets: [],
    demand_enabled: true,
    auto_calibrate_s0: false,
  },
  drinks: [
    { ...DRINK, drink_id: 11, name: 'Bier' },
    { ...DRINK, drink_id: 12, slot: 1, name: 'Wijn' },
    { ...DRINK, drink_id: 13, slot: 2, name: 'Oud', active: false },
  ],
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>
let writeAnswer: () => Response

beforeEach(() => {
  exchangeStore.setState(exchangeStore.getInitialState(), true)
  writeAnswer = () => json(200, { revision: 4, drink_id: 14 })
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (path === '/api/runs/current') {
      return Promise.resolve(json(200, { run_id: 7, name: 'Vrijmibo', status: 'live' }))
    }
    if (method === 'GET') return Promise.resolve(json(200, CONFIG))
    return Promise.resolve(writeAnswer())
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function settle() {
  await act(async () => {})
  await act(async () => {})
}

function writes(): [string, string, unknown][] {
  return (fetchMock.mock.calls as [string, RequestInit | undefined][])
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([path, init]) => [
      path,
      String(init?.method),
      init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    ])
}

async function open() {
  render(<DrinksSection />)
  await settle()
}

const addForm = () => within(screen.getByRole('form', { name: 'Drankje toevoegen' }))
const rowOf = (name: string) => within(screen.getByRole('group', { name }))

function type(scope: ReturnType<typeof within>, label: string, value: string) {
  fireEvent.change(scope.getByLabelText(label), { target: { value } })
}

describe('DrinksSection', () => {
  it('lists the active drinks only', async () => {
    await open()
    expect(screen.getByRole('group', { name: 'Bier' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Wijn' })).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Oud' })).toBeNull()
  })

  it('an add with only name and bounds sends exactly those four keys, in cents (AC4)', async () => {
    await open()
    const form = addForm()
    type(form, 'Naam', 'Cola')
    type(form, 'Min', '1,00')
    type(form, 'Start', '2,50')
    type(form, 'Max', '6')
    fireEvent.click(form.getByRole('button', { name: 'Toevoegen' }))
    await settle()

    expect(writes()).toEqual([
      [
        '/api/runs/7/drinks',
        'POST',
        { name: 'Cola', p_min_cents: 100, p0_cents: 250, p_max_cents: 600 },
      ],
    ])
  })

  it('a filled optional is sent; an invalid one blocks the add', async () => {
    await open()
    const form = addForm()
    type(form, 'Naam', 'Cola')
    type(form, 'Min', '1')
    type(form, 'Start', '2')
    type(form, 'Max', '6')
    type(form, 'Barprijs', '2,505')
    fireEvent.click(form.getByRole('button', { name: 'Toevoegen' }))
    await settle()
    expect(writes()).toEqual([])

    type(form, 'Barprijs', '2,20')
    type(form, 'a', '1,5')
    fireEvent.click(form.getByRole('button', { name: 'Toevoegen' }))
    await settle()
    expect(writes()[0][2]).toEqual({
      name: 'Cola',
      p_min_cents: 100,
      p0_cents: 200,
      p_max_cents: 600,
      bar_price_cents: 220,
      a: 1.5,
    })
  })

  it('a duplicate name shows in Dutch (AC21)', async () => {
    writeAnswer = () => json(409, { error: { code: 'duplicate_drink_name', message: 'exists' } })
    await open()
    const form = addForm()
    type(form, 'Naam', 'bier')
    type(form, 'Min', '1')
    type(form, 'Start', '2')
    type(form, 'Max', '6')
    fireEvent.click(form.getByRole('button', { name: 'Toevoegen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Er is al een drankje met deze naam.')
  })

  it('a rename and a bar price send only what changed', async () => {
    await open()
    const bier = rowOf('Bier')
    fireEvent.click(bier.getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([])

    fireEvent.change(bier.getByLabelText('Naam'), { target: { value: 'Pils' } })
    fireEvent.click(bier.getByRole('button', { name: 'Opslaan' }))
    await settle()
    expect(writes()).toEqual([['/api/runs/7/drinks/11', 'PATCH', { name: 'Pils' }]])
  })

  it('remove asks first: Cancel sends nothing, Confirm sends DELETE (AC39)', async () => {
    await open()
    fireEvent.click(rowOf('Wijn').getByRole('button', { name: 'Verwijderen' }))
    expect(screen.getByRole('dialog', { name: "'Wijn' verwijderen?" })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(writes()).toEqual([])

    fireEvent.click(rowOf('Wijn').getByRole('button', { name: 'Verwijderen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()
    expect(writes()).toEqual([['/api/runs/7/drinks/12', 'DELETE', undefined]])
  })

  it('removing the last active drink shows the refusal in Dutch (AC17)', async () => {
    writeAnswer = () => json(409, { error: { code: 'last_active_drink', message: 'last' } })
    await open()
    fireEvent.click(rowOf('Bier').getByRole('button', { name: 'Verwijderen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await settle()

    expect(screen.getByRole('alert').textContent).toBe('Het laatste actieve drankje kan niet weg.')
  })
})

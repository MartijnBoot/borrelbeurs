// @vitest-environment jsdom
// useEditableRecord (Phase 6 T23: SD27; AC1, AC2, AC3, AC5): the D-03 gate's engine.
// A section edits a copy of the server's record; only the fields that differ are
// ever sent, and an untouched section sends nothing at all.
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { UnsavedEditsProvider, useHasUnsaved } from './unsavedEdits'
import { useEditableRecord } from './useEditableRecord'

interface Params {
  eta: number
  K: number
  demand_enabled: boolean
  idle_targets: number[]
}

const SERVER: Params = { eta: 0.6, K: 12, demand_enabled: true, idle_targets: [1, 2] }

function setup(server: Params | null = SERVER) {
  return renderHook(({ record }) => useEditableRecord(record), {
    initialProps: { record: server },
  })
}

describe('useEditableRecord', () => {
  it('starts from the server record, clean', () => {
    const { result } = setup()
    expect(result.current.values).toEqual(SERVER)
    expect(result.current.dirty).toBe(false)
    expect(result.current.patch).toEqual({})
  })

  it('an untouched record saves as nothing and never sends', async () => {
    const { result } = setup()
    const send = vi.fn()
    await expect(result.current.save(send)).resolves.toBe('nothing')
    expect(send).not.toHaveBeenCalled()
  })

  it('one edited field gives a patch of exactly that key', async () => {
    const { result } = setup()
    act(() => result.current.set('K', 20))
    expect(result.current.patch).toEqual({ K: 20 })
    const send = vi.fn().mockResolvedValue(undefined)
    await act(async () => {
      await expect(result.current.save(send)).resolves.toBe('sent')
    })
    expect(send).toHaveBeenCalledWith({ K: 20 })
  })

  it('a field edited back to the server value is not dirty', () => {
    const { result } = setup()
    act(() => result.current.set('eta', 0.9))
    act(() => result.current.set('eta', 0.6))
    expect(result.current.dirty).toBe(false)
    expect(result.current.patch).toEqual({})
  })

  it('compares lists by content', () => {
    const { result } = setup()
    act(() => result.current.set('idle_targets', [1, 2]))
    expect(result.current.dirty).toBe(false)
    act(() => result.current.set('idle_targets', [2]))
    expect(result.current.patch).toEqual({ idle_targets: [2] })
  })

  it('a cleared or invalid field does not save (AC3)', async () => {
    const { result } = setup()
    const send = vi.fn()
    act(() => result.current.set('eta', null))
    await expect(result.current.save(send)).resolves.toBe('invalid')
    act(() => result.current.set('eta', 'invalid'))
    await expect(result.current.save(send)).resolves.toBe('invalid')
    expect(send).not.toHaveBeenCalled()
  })

  it('reloads a server change while clean', () => {
    const { result, rerender } = setup()
    rerender({ record: { ...SERVER, eta: 0.7 } })
    expect(result.current.values?.eta).toBe(0.7)
    expect(result.current.conflict).toBe(false)
  })

  it('keeps the input and flags a conflict on a server change while dirty (AC5)', () => {
    const { result, rerender } = setup()
    act(() => result.current.set('K', 20))

    rerender({ record: { ...SERVER, eta: 0.7 } })

    expect(result.current.conflict).toBe(true)
    expect(result.current.values).toEqual({ ...SERVER, K: 20 })
    act(() => result.current.takeServer())
    expect(result.current.values).toEqual({ ...SERVER, eta: 0.7 })
    expect(result.current.dirty).toBe(false)
    expect(result.current.conflict).toBe(false)
  })

  it('a server echo of the saved edit is no conflict', () => {
    const { result, rerender } = setup()
    act(() => result.current.set('K', 20))
    rerender({ record: { ...SERVER, K: 20 } })
    expect(result.current.conflict).toBe(false)
    expect(result.current.dirty).toBe(false)
  })

  it('reset discards the edits', () => {
    const { result } = setup()
    act(() => result.current.set('K', 20))
    act(() => result.current.reset())
    expect(result.current.values).toEqual(SERVER)
    expect(result.current.dirty).toBe(false)
  })

  it('waits for a server record before it has values', () => {
    const { result, rerender } = setup(null)
    expect(result.current.values).toBeNull()
    rerender({ record: SERVER })
    expect(result.current.values).toEqual(SERVER)
  })

  // B-12 PD2: the leave guard hears from every record while it is dirty.
  it('reports itself unsaved while dirty, and stops after a save or a reset', () => {
    let server: Params = SERVER
    const { result, rerender } = renderHook(
      () => ({ record: useEditableRecord(server), unsaved: useHasUnsaved() }),
      { wrapper: UnsavedEditsProvider },
    )
    expect(result.current.unsaved).toBe(false)

    act(() => result.current.record.set('K', 20))
    expect(result.current.unsaved).toBe(true)
    act(() => result.current.record.reset())
    expect(result.current.unsaved).toBe(false)

    act(() => result.current.record.set('K', 20))
    server = { ...SERVER, K: 20 } // the save's echo
    rerender()
    expect(result.current.unsaved).toBe(false)
  })

  it('a refetch with the same content while dirty is not a conflict (AC5)', () => {
    const { result, rerender } = setup()
    act(() => result.current.set('K', 20))
    rerender({ record: { ...SERVER, idle_targets: [1, 2] } })
    expect(result.current.conflict).toBe(false)
    expect(result.current.patch).toEqual({ K: 20 })
  })
})

/**
 * The React binding for the bar controller (Phase 5 PD8): one controller per
 * page mount, with the real monotonic clock, timers, transport and uuids.
 *
 * Created and disposed in one effect, as `app/providers.tsx` does the
 * exchange client, so StrictMode's mount-unmount-mount leaves exactly one
 * running. The effect publishes the live controller into a small per-mount
 * slot that `useSyncExternalStore` reads; the actions forward to whichever
 * controller is live, so their identities never change. Before the effect
 * runs, the view is empty and every action is a no-op.
 */
import { useEffect, useState, useSyncExternalStore } from 'react'
import { exchangeStore, type DrinkId } from '../exchange'
import { postOrder } from './api/orders'
import { createBarController, type BarController, type BarView } from './model/barController'
import type { PressId } from './model/holdBuffer'

export interface BarActions {
  press(id?: PressId): void
  release(id?: PressId): void
  tap(drinkId: DrinkId): void
  refresh(): void
  confirm(): void
  cancel(): void
  retry(id: number): void
  dismiss(id: number): void
}

const EMPTY_VIEW: BarView = Object.freeze({
  displayed: null,
  latest: null,
  entries: [],
  headConflict: null,
})

function createSlot() {
  let controller: BarController | null = null
  const listeners = new Set<() => void>()
  let detach = () => {}
  const notify = () => listeners.forEach((listener) => listener())
  const actions: BarActions = {
    press: (id) => controller?.press(id),
    release: (id) => controller?.release(id),
    tap: (drinkId) => void controller?.tap(drinkId),
    refresh: () => controller?.refresh(),
    confirm: () => controller?.confirm(),
    cancel: () => controller?.cancel(),
    retry: (id) => controller?.retry(id),
    dismiss: (id) => controller?.dismiss(id),
  }
  return {
    actions,
    set(next: BarController | null) {
      detach()
      controller = next
      detach = next === null ? () => {} : next.subscribe(notify)
      notify()
    },
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    view: (): BarView => controller?.view ?? EMPTY_VIEW,
  }
}

export function useBarController(): { view: BarView; actions: BarActions } {
  const [slot] = useState(createSlot)
  useEffect(() => {
    const controller = createBarController({
      store: exchangeStore,
      now: () => performance.now(),
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: (id) => window.clearTimeout(id),
      post: postOrder,
      uuid: () => crypto.randomUUID(),
    })
    slot.set(controller)
    return () => {
      slot.set(null)
      controller.dispose()
    }
  }, [slot])
  const view = useSyncExternalStore(slot.subscribe, slot.view)
  return { view, actions: slot.actions }
}

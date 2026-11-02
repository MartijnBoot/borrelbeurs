/**
 * Which forms hold typed values that differ from what is stored (B-12 SD9,
 * PD2). A form reports with `useReportUnsaved(dirty)`: it is counted while
 * `dirty` is true and stops counting when it turns false or the form unmounts.
 * `useHasUnsaved()` is true while any form is counted. Without a provider a
 * report does nothing and nothing is unsaved, so a form can report wherever
 * it is mounted. `LeaveGuard` decides what to do about it.
 */
import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

interface Registry {
  add(id: string): void
  remove(id: string): void
}

const RegistryContext = createContext<Registry | null>(null)
const UnsavedContext = createContext(false)

export function UnsavedEditsProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<ReadonlySet<string>>(new Set())
  const registry = useMemo<Registry>(
    () => ({
      add: (id) => setIds((held) => (held.has(id) ? held : new Set(held).add(id))),
      remove: (id) =>
        setIds((held) => {
          if (!held.has(id)) return held
          const next = new Set(held)
          next.delete(id)
          return next
        }),
    }),
    [],
  )
  return createElement(
    RegistryContext.Provider,
    { value: registry },
    createElement(UnsavedContext.Provider, { value: ids.size > 0 }, children),
  )
}

export function useReportUnsaved(dirty: boolean): void {
  const registry = useContext(RegistryContext)
  const id = useId()
  useEffect(() => {
    if (registry === null || !dirty) return
    registry.add(id)
    return () => registry.remove(id)
  }, [registry, dirty, id])
}

export function useHasUnsaved(): boolean {
  return useContext(UnsavedContext)
}

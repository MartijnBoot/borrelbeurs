/**
 * `useConfirmLeave()(then)` (B-12 PD3): runs `then` once the person has agreed
 * to drop their unsaved edits, or at once when there are none. `LeaveGuard`
 * provides it; without one, `then` runs at once.
 */
import { createContext, useContext } from 'react'

export type ConfirmLeave = (then: () => void) => void

export const ConfirmLeaveContext = createContext<ConfirmLeave>((then) => then())

export function useConfirmLeave(): ConfirmLeave {
  return useContext(ConfirmLeaveContext)
}

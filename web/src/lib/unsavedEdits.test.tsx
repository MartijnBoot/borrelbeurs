// @vitest-environment jsdom
// The unsaved-edits registry (B-12 T2: SD9, PD2).
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { UnsavedEditsProvider, useHasUnsaved, useReportUnsaved } from './unsavedEdits'

afterEach(cleanup)

function Form({ dirty }: { dirty: boolean }) {
  useReportUnsaved(dirty)
  return null
}

function Probe() {
  return <output data-testid="unsaved">{String(useHasUnsaved())}</output>
}

// Each form: `true` dirty, `false` clean, `null` unmounted.
function renderForms(forms: (boolean | null)[]) {
  const ui = (held: (boolean | null)[]) => (
    <UnsavedEditsProvider>
      {held.map((dirty, i) => dirty !== null && <Form key={i} dirty={dirty} />)}
      <Probe />
    </UnsavedEditsProvider>
  )
  const { rerender } = render(ui(forms))
  return (next: (boolean | null)[]) => rerender(ui(next))
}

const unsaved = () => screen.getByTestId('unsaved').textContent

describe('unsaved edits (B-12 PD2)', () => {
  it('counts a form while it is dirty, and until the last one is clean', () => {
    const update = renderForms([false, false])
    expect(unsaved()).toBe('false')

    update([true, false])
    expect(unsaved()).toBe('true')
    update([true, true])
    update([false, true])
    expect(unsaved()).toBe('true')
    update([false, false])
    expect(unsaved()).toBe('false')
  })

  it('stops counting a form that unmounts', () => {
    const update = renderForms([true, false])
    expect(unsaved()).toBe('true')
    update([null, false])
    expect(unsaved()).toBe('false')
  })

  it('is a no-op without a provider', () => {
    render(
      <>
        <Form dirty />
        <Probe />
      </>,
    )
    expect(unsaved()).toBe('false')
  })
})

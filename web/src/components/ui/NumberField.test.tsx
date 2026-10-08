// @vitest-environment jsdom
// NumberField (Phase 6 T21, SD27; AC1, AC3): empty is `null`, never 0; an invalid
// entry reports 'invalid', never a number; an untouched field reports nothing.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NumberField } from './NumberField'

afterEach(cleanup)

function renderField(value: number | null = 0.6) {
  const onChange = vi.fn()
  const view = render(<NumberField label="Snelheid" value={value} onChange={onChange} />)
  return { onChange, input: screen.getByLabelText('Snelheid') as HTMLInputElement, ...view }
}

describe('NumberField', () => {
  it('shows the value it is given, with a decimal comma', () => {
    expect(renderField(0.6).input.value).toBe('0,6')
  })

  it('shows null as empty', () => {
    expect(renderField(null).input.value).toBe('')
  })

  it('reports nothing while untouched', () => {
    const { onChange } = renderField()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('reports null when cleared, never 0', () => {
    const { onChange, input } = renderField()
    fireEvent.change(input, { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it.each([
    ['0,9', 0.9],
    ['0.9', 0.9],
    ['12', 12],
    ['-1,5', -1.5],
  ])('reports %j as %j', (text, number) => {
    const { onChange, input } = renderField()
    fireEvent.change(input, { target: { value: text } })
    expect(onChange).toHaveBeenLastCalledWith(number)
  })

  it.each(['abc', '1,2,3', '1e3', '--1', '1,'])(
    'reports %j as invalid and keeps the text',
    (text) => {
      const { onChange, input } = renderField()
      fireEvent.change(input, { target: { value: text } })
      expect(onChange).toHaveBeenLastCalledWith('invalid')
      expect(input.value).toBe(text)
    },
  )

  it('takes a new value from its owner', () => {
    const { input, rerender, onChange } = renderField(0.6)
    rerender(<NumberField label="Snelheid" value={0.75} onChange={onChange} />)
    expect(input.value).toBe('0,75')
  })

  it('shows its hint and error', () => {
    const onChange = vi.fn()
    render(
      <NumberField
        label="Drempel"
        value={null}
        onChange={onChange}
        hint="groter dan 0"
        error="Verplicht"
      />,
    )
    const input = screen.getByLabelText('Drempel')
    expect(screen.getByText('groter dan 0')).toBeTruthy()
    expect(screen.getByText('Verplicht')).toBeTruthy()
    expect(input.getAttribute('aria-invalid')).toBe('true')
  })
})

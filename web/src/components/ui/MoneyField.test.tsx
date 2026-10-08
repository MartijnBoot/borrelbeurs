// @vitest-environment jsdom
// MoneyField (Phase 6 T21, SD5, SD27; AC1, AC3): cents in and out, through
// `parseEuroCents`; "2,50" is 250 exactly; three decimals is invalid, never rounded.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MoneyField } from './MoneyField'

afterEach(cleanup)

function renderField(cents: number | null = 250) {
  const onChange = vi.fn()
  const view = render(<MoneyField label="Startprijs" cents={cents} onChange={onChange} />)
  return { onChange, input: screen.getByLabelText('Startprijs') as HTMLInputElement, ...view }
}

describe('MoneyField', () => {
  it('shows cents as euros with a comma', () => {
    expect(renderField(250).input.value).toBe('2,50')
    cleanup()
    expect(renderField(5).input.value).toBe('0,05')
    cleanup()
    expect(renderField(null).input.value).toBe('')
  })

  it('reports nothing while untouched', () => {
    expect(renderField().onChange).not.toHaveBeenCalled()
  })

  it.each([
    ['2,50', 250],
    ['2.50', 250],
    ['3', 300],
    ['', null],
  ])('reports %j as %j', (text, cents) => {
    // From 1,00: an input whose text does not change fires no change event.
    const { onChange, input } = renderField(100)
    fireEvent.change(input, { target: { value: text } })
    expect(onChange).toHaveBeenLastCalledWith(cents)
  })

  it('reports three decimals as invalid, never rounded', () => {
    const { onChange, input } = renderField()
    fireEvent.change(input, { target: { value: '2,505' } })
    expect(onChange).toHaveBeenLastCalledWith('invalid')
    expect(input.value).toBe('2,505')
  })

  it('takes new cents from its owner', () => {
    const { input, rerender, onChange } = renderField(250)
    rerender(<MoneyField label="Startprijs" cents={310} onChange={onChange} />)
    expect(input.value).toBe('3,10')
  })
})

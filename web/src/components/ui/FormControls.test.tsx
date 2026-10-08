// @vitest-environment jsdom
// Select, Switch, Toast and MobileSectionNav (Phase 6 T22: SD25, SD27; AC2).
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MobileSectionNav } from './MobileSectionNav'
import { Select } from './Select'
import { Switch } from './Switch'
import { Toast } from './Toast'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

describe('Select', () => {
  it('is labelled, shows its value and reports a choice', () => {
    const onChange = vi.fn()
    render(
      <Select
        label="Lettertype"
        value="inter"
        options={[
          { value: 'inter', label: 'Inter' },
          { value: 'garamond', label: 'EB Garamond' },
        ]}
        onChange={onChange}
      />,
    )
    const select = screen.getByLabelText('Lettertype') as HTMLSelectElement
    expect(select.value).toBe('inter')
    fireEvent.change(select, { target: { value: 'garamond' } })
    expect(onChange).toHaveBeenCalledWith('garamond')
  })
})

describe('Switch', () => {
  it('toggles aria-checked through its owner', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <Switch label="Vraag/aanbod actief" checked={false} onChange={onChange} />,
    )
    const toggle = screen.getByRole('switch', { name: 'Vraag/aanbod actief' })
    expect(toggle.getAttribute('aria-checked')).toBe('false')

    fireEvent.click(toggle)

    expect(onChange).toHaveBeenCalledWith(true)
    rerender(<Switch label="Vraag/aanbod actief" checked onChange={onChange} />)
    expect(toggle.getAttribute('aria-checked')).toBe('true')
  })
})

describe('Toast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('shows its text, then hides after its timeout', () => {
    const onDone = vi.fn()
    render(<Toast message="Niets te wijzigen" onDone={onDone} />)
    expect(screen.getByRole('status').textContent).toBe('Niets te wijzigen')

    act(() => {
      vi.advanceTimersByTime(3_000)
    })

    expect(onDone).toHaveBeenCalledOnce()
  })

  it('shows nothing without a message', () => {
    render(<Toast message={null} onDone={() => {}} />)
    expect(screen.queryByRole('status')).toBeNull()
  })
})

describe('MobileSectionNav', () => {
  const sections = [
    { id: 'borrel', label: 'Borrel' },
    { id: 'thema', label: '🎨 Kleurenschema' },
  ]

  it('renders in-page links on a wide screen', () => {
    stubMatchMedia(false)
    render(<MobileSectionNav sections={sections} />)
    const link = screen.getByRole('link', { name: '🎨 Kleurenschema' })
    expect(link.getAttribute('href')).toBe('#thema')
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('renders a select when the narrow query matches', () => {
    stubMatchMedia(true)
    render(<MobileSectionNav sections={sections} />)
    const select = screen.getByRole('combobox', { name: 'Sectie' }) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toEqual(['Borrel', '🎨 Kleurenschema'])
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('jumps to the chosen section', () => {
    stubMatchMedia(true)
    const target = document.createElement('section')
    target.id = 'thema'
    target.scrollIntoView = vi.fn()
    document.body.appendChild(target)
    render(<MobileSectionNav sections={sections} />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'thema' } })

    expect(target.scrollIntoView).toHaveBeenCalled()
    target.remove()
  })
})

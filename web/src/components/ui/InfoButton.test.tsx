// @vitest-environment jsdom
// The (i) and its popup (B-01 T2: SD1; AC1-AC5, AC6's placement).
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { FormEvent } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type Explanation, InfoButton } from './InfoButton'
import { expectExplained } from './infoTesting'
import { NumberField } from './NumberField'
import { placePopup } from './placePopup'

afterEach(cleanup)

const STEP: Explanation = {
  name: 'Prijsstap (€)',
  paragraphs: ['Eerste alinea.', 'Hoger: grotere stappen.', 'Eerste borrel: 0,10.'],
}
const ETA: Explanation = { name: 'Beweging per bestelling', paragraphs: ['Hoe groot.'] }

const info = (name: string) => screen.getByRole('button', { name: `Uitleg: ${name}` })
const popup = (name: string) => screen.queryByRole('note', { name })

describe('InfoButton', () => {
  it('opens on click with the name as title and one paragraph per line', () => {
    render(<InfoButton explanation={STEP} />)
    expect(popup(STEP.name)).toBeNull()

    fireEvent.click(info(STEP.name))

    const box = popup(STEP.name)
    expect(box).not.toBeNull()
    expect([...box!.querySelectorAll('p')].map((p) => p.textContent)).toEqual([
      STEP.name,
      ...STEP.paragraphs,
    ])
  })

  it('closes on a second click, an outside click and Escape', () => {
    render(
      <>
        <InfoButton explanation={STEP} />
        <span>buiten</span>
      </>,
    )
    fireEvent.click(info(STEP.name))
    fireEvent.click(info(STEP.name))
    expect(popup(STEP.name)).toBeNull()

    fireEvent.click(info(STEP.name))
    fireEvent.click(screen.getByText('buiten'))
    expect(popup(STEP.name)).toBeNull()

    fireEvent.click(info(STEP.name))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(popup(STEP.name)).toBeNull()
  })

  it('stays open on a click inside the popup', () => {
    render(<InfoButton explanation={STEP} />)
    fireEvent.click(info(STEP.name))
    fireEvent.click(screen.getByText('Hoger: grotere stappen.'))
    expect(popup(STEP.name)).not.toBeNull()
  })

  it('opening another closes the first: at most one is open', () => {
    render(
      <>
        <InfoButton explanation={STEP} />
        <InfoButton explanation={ETA} />
      </>,
    )
    fireEvent.click(info(STEP.name))
    fireEvent.click(info(ETA.name))

    expect(popup(STEP.name)).toBeNull()
    expect(popup(ETA.name)).not.toBeNull()
    expect(screen.getAllByRole('note')).toHaveLength(1)
    expect(info(STEP.name).getAttribute('aria-expanded')).toBe('false')
  })

  it('does not open on hover', () => {
    render(<InfoButton explanation={STEP} />)
    fireEvent.mouseOver(info(STEP.name))
    fireEvent.mouseEnter(info(STEP.name))
    fireEvent.pointerEnter(info(STEP.name))
    expect(popup(STEP.name)).toBeNull()
  })

  it('is a native button, so Enter and Space open it, and focus stays on it after Escape', () => {
    render(<InfoButton explanation={STEP} />)
    const button = info(STEP.name)
    // A <button> turns Enter and Space into a click; jsdom does not synthesise
    // that activation, so the click is dispatched the way the browser would.
    expect(button.tagName).toBe('BUTTON')
    expect(button.getAttribute('type')).toBe('button')
    button.focus()
    fireEvent.keyDown(button, { key: 'Enter' })
    fireEvent.click(button)
    expect(popup(STEP.name)).not.toBeNull()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(popup(STEP.name)).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('is named "Uitleg: {name}" and reflects its state in aria-expanded', () => {
    render(<InfoButton explanation={STEP} />)
    const button = info(STEP.name)
    expect(button.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(button)
    expect(button.getAttribute('aria-expanded')).toBe('true')
    expect(button.getAttribute('aria-controls')).toBe(popup(STEP.name)!.id)
  })

  it('inside a form, neither submits it nor changes the field next to it', () => {
    const onSubmit = vi.fn((event: FormEvent) => event.preventDefault())
    const onChange = vi.fn()
    render(
      <form onSubmit={onSubmit}>
        <NumberField label={STEP.name} value={0.1} onChange={onChange} info={STEP} />
        <button type="submit">Opslaan</button>
      </form>,
    )
    fireEvent.click(info(STEP.name))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(onSubmit).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
    expect((screen.getByLabelText(STEP.name) as HTMLInputElement).value).toBe('0,1')
  })

  it('expectExplained opens, checks and closes it', () => {
    const { container } = render(<InfoButton explanation={STEP} />)
    expectExplained(container, STEP)
    expect(popup(STEP.name)).toBeNull()
  })
})

describe('placePopup (AC6)', () => {
  const phone = { width: 360, height: 800 }
  const popupSize = { width: 320, height: 200 }

  it('keeps the box inside 8..352 for an anchor at the right edge of a 360 px screen', () => {
    const { left } = placePopup({ left: 340, top: 100, bottom: 120 }, popupSize, phone)
    expect(left).toBeGreaterThanOrEqual(8)
    expect(left + popupSize.width).toBeLessThanOrEqual(352)
  })

  it('keeps the box inside for an anchor at the left edge', () => {
    expect(placePopup({ left: 0, top: 100, bottom: 120 }, popupSize, phone).left).toBe(8)
  })

  it('goes below the anchor when it fits, above when it does not', () => {
    expect(placePopup({ left: 20, top: 100, bottom: 120 }, popupSize, phone).top).toBe(126)
    expect(placePopup({ left: 20, top: 700, bottom: 720 }, popupSize, phone).top).toBe(494)
  })

  it('stays on screen when it fits neither below nor above', () => {
    const tall = { width: 320, height: 600 }
    const { top } = placePopup({ left: 20, top: 400, bottom: 420 }, tall, phone)
    expect(top).toBeGreaterThanOrEqual(8)
    expect(top + tall.height).toBeLessThanOrEqual(792)
  })
})

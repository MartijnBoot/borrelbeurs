/**
 * Test helper for B-01's explanations (T2, used by T5-T10): opens the (i)
 * named "Uitleg: {name}" inside `scope`, asserts the popup carries exactly the
 * entry's title and paragraphs, then closes it with Escape. The popup lives in
 * `body` (a portal), so it is looked up on the whole screen.
 */
import { fireEvent, screen, within } from '@testing-library/react'
import { expect } from 'vitest'
import type { Explanation } from './InfoButton'

export function expectExplained(scope: HTMLElement, explanation: Explanation) {
  const button = within(scope).getByRole('button', { name: `Uitleg: ${explanation.name}` })
  expect(button.getAttribute('aria-expanded')).toBe('false')

  fireEvent.click(button)

  const popup = screen.getByRole('note', { name: explanation.name })
  expect([...popup.querySelectorAll('p')].map((p) => p.textContent)).toEqual([
    explanation.name,
    ...explanation.paragraphs,
  ])
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('note', { name: explanation.name })).toBeNull()
  expect(button.getAttribute('aria-expanded')).toBe('false')
}

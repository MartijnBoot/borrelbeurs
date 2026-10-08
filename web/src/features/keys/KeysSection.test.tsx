// @vitest-environment jsdom
// The keys section stub (Phase 6 T24); T32 replaces it.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { KeysSection } from './KeysSection'

afterEach(cleanup)

it('says it is not built yet', () => {
  render(<KeysSection />)
  expect(screen.getByText('Nog niet beschikbaar')).toBeTruthy()
})

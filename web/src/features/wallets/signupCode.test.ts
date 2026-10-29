// Whether a save breaks printed sign-up codes (B-09 SD7, SD9; AC11, AC12, AC14).
import { describe, expect, it } from 'vitest'
import { breaksPrinted } from './signupCode'

describe('breaksPrinted', () => {
  it.each([
    // No code saved: nothing printed can break (AC14).
    [null, 'X', null],
    [null, '', null],
    [null, null, null],
    // The same code under the server's comparison (AC14).
    ['BORREL', 'borrel', null],
    ['BORREL', ' BORREL ', null],
    // A different code (AC11).
    ['BORREL', 'ANDERS', 'change'],
    // Cleared, by "Wissen" or a blank field (AC12).
    ['BORREL', '', 'clear'],
    ['BORREL', '   ', 'clear'],
    ['BORREL', null, 'clear'],
    // SD9: `toLowerCase` does not fold ß, so this asks once more than the server needs.
    ['Straße', 'STRASSE', 'change'],
  ] as const)('saved %j, next %j → %j', (saved, next, expected) => {
    expect(breaksPrinted(saved, next)).toBe(expected)
  })
})

/**
 * B-07 T8 (AC16, SD11): E1, E17 and E19 as the settings page imports them. The
 * full text is pinned to the spec by `tests/unit/test_setting_explanations_text.py`;
 * this checks the bundle the page renders carries B-07's sentences.
 */
import { describe, expect, it } from 'vitest'

import explanations from './explanations.json'

describe('B-07 explanations', () => {
  it('Prijsstap says the bounds move inward with it', () => {
    const text = explanations.step_quant.paragraphs.join(' ')
    expect(explanations.step_quant.id).toBe('E1')
    expect(text).toContain('Minimumprijs en Maximumprijs zijn ook een veelvoud van de Prijsstap')
    expect(text).toContain('schuiven ze mee naar binnen')
    expect(text).toContain('geen ruimte meer heeft tussen Minimumprijs, Startprijs en Maximumprijs')
  })

  it.each([
    ['p_min_cents', 'E17', 'Toegestaan: 0 of meer, een veelvoud van de Prijsstap'],
    ['p_max_cents', 'E19', 'Toegestaan: een veelvoud van de Prijsstap'],
  ] as const)('%s requires a multiple of the Prijsstap', (key, id, allowed) => {
    const entry = explanations[key]
    expect(entry.id).toBe(id)
    expect(entry.paragraphs.join(' ')).toContain(allowed)
    expect(entry.paragraphs.join(' ')).not.toContain('Kies hem als veelvoud van de Prijsstap')
  })
})

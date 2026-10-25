// The decoder's round trip (B-05 SD18, AC43): a token the player page's generator
// encodes, painted as a camera frame, decodes back with the approved decoder.
import { encode } from 'uqr'
import { describe, expect, it } from 'vitest'
import { decode, type Frame } from './decodeQr'

// As `features/player/QrCode.tsx` draws it (a feature may not import another).
const AS_DRAWN = { ecc: 'M', border: 2 } as const
const PX = 8

function paint(modules: boolean[][], px = PX): Frame {
  const width = modules.length * px
  const data = new Uint8ClampedArray(width * width * 4)
  for (let y = 0; y < width; y++) {
    for (let x = 0; x < width; x++) {
      const value = modules[Math.floor(y / px)][Math.floor(x / px)] ? 0 : 255
      data.set([value, value, value, 255], (y * width + x) * 4)
    }
  }
  return { data, width, height: width }
}

describe('decode (AC43)', () => {
  it.each(['q2h5bq0V3cXhT7zZp1kY9w', 'A-_aB-_0123456789xyzQ', 'kort'])(
    'reads back %s from the drawn code',
    async (token) => {
      expect(await decode(paint(encode(token, AS_DRAWN).data))).toBe(token)
    },
  )

  it('reads nothing from noise', async () => {
    let seed = 7
    const random = () => (seed = (seed * 48271) % 2147483647) / 2147483647
    const noise = Array.from({ length: 40 }, () => Array.from({ length: 40 }, () => random() < 0.5))
    expect(await decode(paint(noise))).toBeNull()
  })

  it('reads nothing from a blank frame', async () => {
    const blank = Array.from({ length: 30 }, () => Array.from({ length: 30 }, () => false))
    expect(await decode(paint(blank))).toBeNull()
  })
})

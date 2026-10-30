// @vitest-environment jsdom
// The sign-up QR code's two files (B-09 AC4–AC7): both made from one `uqr` matrix,
// both decode back to the link, and the PNG is an opaque, two-colour raster.
import { cleanup, render } from '@testing-library/react'
import jsQR from 'jsqr'
import { createElement } from 'react'
import { encode } from 'uqr'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QrSvg } from './QrSvg'
import { pngBlob, qrPixels, saveFile, svgDocument, type Modules } from './qrFiles'

afterEach(cleanup)

// As the sign-up section encodes it (SD4); a feature may not be imported from here.
const SIGNUP = { ecc: 'Q', border: 4 } as const

const ORIGINS = ['http://192.168.8.10', 'https://borrelbeurs.onrender.com']
const CODES = ['BORREL', 'a b&c#é', 'Z'.repeat(20) + '0123456789abcdefghij']
const LINKS = ORIGINS.flatMap((origin) =>
  CODES.map((code) => `${origin}/speler?code=${encodeURIComponent(code)}`),
)

function readQr(frame: { data: Uint8ClampedArray; width: number; height: number }) {
  return jsQR(frame.data, frame.width, frame.height, { inversionAttempts: 'dontInvert' })?.data
}

// The test's own SVG rasteriser: the white background first, then each black rect.
function rasteriseSvg(svgText: string, k = 8) {
  const svg = new DOMParser().parseFromString(svgText, 'image/svg+xml').documentElement
  const [, , n] = svg.getAttribute('viewBox')!.split(' ').map(Number)
  const width = n * k
  const data = new Uint8ClampedArray(width * width * 4)
  for (const rect of Array.from(svg.querySelectorAll('rect'))) {
    const value = rect.getAttribute('fill') === '#fff' ? 255 : 0
    const [x, y, w, h] = ['x', 'y', 'width', 'height'].map((a) => Number(rect.getAttribute(a)))
    for (let py = y * k; py < (y + h) * k; py++) {
      for (let px = x * k; px < (x + w) * k; px++) {
        data.set([value, value, value, 255], (py * width + px) * 4)
      }
    }
  }
  return { data, width, height: width }
}

function sameBytes(a: Uint8ClampedArray, b: Uint8ClampedArray) {
  return a.length === b.length && a.every((value, i) => value === b[i])
}

function blackRects(svgText: string) {
  const svg = new DOMParser().parseFromString(svgText, 'image/svg+xml').documentElement
  return Array.from(svg.querySelectorAll('rect')).filter((r) => r.getAttribute('fill') === '#000')
}

function asMatrix(n: number, cells: { x: number; y: number }[]): boolean[][] {
  const matrix = Array.from({ length: n }, () => Array.from({ length: n }, () => false))
  for (const { x, y } of cells) matrix[y][x] = true
  return matrix
}

function rectCells(rects: Element[]) {
  return rects.map((r) => ({ x: Number(r.getAttribute('x')), y: Number(r.getAttribute('y')) }))
}

describe('decoding (AC4)', () => {
  it.each(LINKS)('the PNG raster and the SVG both read back %s', (link) => {
    const modules = encode(link, SIGNUP).data
    expect(readQr(qrPixels(modules))).toBe(link)
    expect(readQr(rasteriseSvg(svgDocument(modules)))).toBe(link)
  })
})

describe('the same modules (AC5)', () => {
  it.each(LINKS)('raster, SVG file and preview all draw %s exactly', (link) => {
    const modules = encode(link, SIGNUP).data
    const n = modules.length

    const { data, width } = qrPixels(modules)
    const k = width / n
    const sampled = modules.map((row, y) =>
      row.map((_, x) => {
        const centre = ((y * k + Math.floor(k / 2)) * width + x * k + Math.floor(k / 2)) * 4
        return data[centre] === 0
      }),
    )
    expect(sampled).toEqual(modules)

    expect(asMatrix(n, rectCells(blackRects(svgDocument(modules))))).toEqual(modules)

    const { container } = render(createElement(QrSvg, { modules, label: 'Voorbeeld' }))
    const preview = container.querySelector('svg')!
    expect(preview.getAttribute('viewBox')).toBe(`0 0 ${n} ${n}`)
    expect(asMatrix(n, rectCells(Array.from(preview.querySelectorAll('rect'))))).toEqual(modules)
    cleanup()

    // The quiet zone: the outermost four rows and columns are light.
    for (let i = 0; i < n; i++) {
      for (let edge = 0; edge < 4; edge++) {
        expect(modules[edge][i]).toBe(false)
        expect(modules[n - 1 - edge][i]).toBe(false)
        expect(modules[i][edge]).toBe(false)
        expect(modules[i][n - 1 - edge]).toBe(false)
      }
    }
  })

  it('the preview is an image named by its label', () => {
    const modules = encode(LINKS[0], SIGNUP).data
    const { getByRole } = render(createElement(QrSvg, { modules, label: 'Aanmeld-QR-code' }))
    const svg = getByRole('img', { name: 'Aanmeld-QR-code' })
    expect(svg.getAttribute('shape-rendering')).toBe('crispEdges')
    expect(
      new Set(Array.from(svg.querySelectorAll('rect'), (r) => r.getAttribute('fill'))),
    ).toEqual(new Set(['#000']))
  })
})

describe('the PNG raster (AC6)', () => {
  it.each(LINKS)('is square, at most 1024 px, opaque and two-colour for %s', (link) => {
    const modules = encode(link, SIGNUP).data
    const n = modules.length
    const k = Math.floor(1024 / n)
    const { data, width, height } = qrPixels(modules)

    expect(width).toBe(n * k)
    expect(height).toBe(width)
    expect(width).toBeLessThanOrEqual(1024)
    expect(width).toBeGreaterThan(1024 - n)
    expect(data).toHaveLength(width * height * 4)

    // Gathered by hand and asserted once: an expect per pixel takes seconds.
    const alphas = new Set<number>()
    const colours = new Set<string>()
    for (let i = 0; i < data.length; i += 4) {
      alphas.add(data[i + 3])
      colours.add(`${data[i]},${data[i + 1]},${data[i + 2]}`)
    }
    expect(alphas).toEqual(new Set([255]))
    expect(colours).toEqual(new Set(['0,0,0', '255,255,255']))

    for (let by = 0; by < n; by++) {
      for (let bx = 0; bx < n; bx++) {
        const first = data[(by * k * width + bx * k) * 4]
        for (let y = by * k; y < (by + 1) * k; y++) {
          for (let x = bx * k; x < (bx + 1) * k; x++) {
            if (data[(y * width + x) * 4] !== first) throw new Error(`block ${bx},${by} is mixed`)
          }
        }
      }
    }
  })
})

describe('the SVG text (AC7)', () => {
  it('is a standalone, number-only document', () => {
    const modules = encode(LINKS[1], SIGNUP).data
    const n = modules.length
    const text = svgDocument(modules)

    expect(text.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true)
    expect(text).toContain(`viewBox="0 0 ${n} ${n}"`)
    expect(text).toContain('shape-rendering="crispEdges"')

    const svg = new DOMParser().parseFromString(text, 'image/svg+xml').documentElement
    const [background] = Array.from(svg.querySelectorAll('rect'))
    expect(background.getAttribute('fill')).toBe('#fff')
    expect(['x', 'y'].map((a) => background.getAttribute(a) ?? '0')).toEqual(['0', '0'])
    expect(background.getAttribute('width')).toBe(String(n))
    expect(background.getAttribute('height')).toBe(String(n))

    expect(blackRects(text)).toHaveLength(modules.flat().filter(Boolean).length)
    for (const banned of ['<text', '<script', '<image', 'href']) expect(text).not.toContain(banned)
    expect(text.replace('http://www.w3.org/2000/svg', '')).not.toContain('http')
  })
})

describe('pngBlob', () => {
  const modules: Modules = encode(LINKS[0], SIGNUP).data

  function stubCanvas(blob: Blob | null) {
    const putImageData = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      putImageData,
    } as unknown as CanvasRenderingContext2D)
    const toBlob = vi
      .spyOn(HTMLCanvasElement.prototype, 'toBlob')
      .mockImplementation(function (callback) {
        callback(blob)
      })
    // jsdom has no ImageData without a canvas package; a stand-in records what it is given.
    vi.stubGlobal(
      'ImageData',
      function (this: object, data: Uint8ClampedArray, width: number, height: number) {
        Object.assign(this, { data, width, height })
      },
    )
    return { putImageData, toBlob }
  }

  afterEach(() => vi.unstubAllGlobals())

  it('puts exactly the raster on a canvas of its size and asks for a PNG', async () => {
    const png = new Blob(['png'], { type: 'image/png' })
    const { putImageData, toBlob } = stubCanvas(png)
    const expected = qrPixels(modules)

    await expect(pngBlob(modules)).resolves.toBe(png)

    const canvas = toBlob.mock.contexts[0] as HTMLCanvasElement
    expect([canvas.width, canvas.height]).toEqual([expected.width, expected.height])
    expect(toBlob.mock.calls[0][1]).toBe('image/png')
    const [image, x, y] = putImageData.mock.calls[0]
    expect([x, y]).toEqual([0, 0])
    expect([image.width, image.height]).toEqual([expected.width, expected.height])
    expect(sameBytes(image.data, expected.data)).toBe(true)
  })

  it('rejects when the canvas gives no blob', async () => {
    stubCanvas(null)
    await expect(pngBlob(modules)).rejects.toThrow()
  })

  it('rejects when there is no 2d context', async () => {
    stubCanvas(null)
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    await expect(pngBlob(modules)).rejects.toThrow()
  })
})

describe('saveFile', () => {
  it('clicks a download anchor for a blob URL and revokes it 40 s later', async () => {
    // jsdom has neither function, so they are put on URL for this test and taken off again.
    const { createObjectURL, revokeObjectURL } = URL
    const create = vi.fn(() => 'blob:http://signup.test/1')
    const revoke = vi.fn()
    URL.createObjectURL = create
    URL.revokeObjectURL = revoke
    vi.useFakeTimers()
    try {
      const clicks: HTMLAnchorElement[] = []
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
        this: HTMLAnchorElement,
      ) {
        clicks.push(this)
      })
      const blob = new Blob(['x'], { type: 'image/svg+xml' })

      saveFile(blob, 'aanmelden-signup.test-BORREL.svg')

      expect(create).toHaveBeenCalledWith(blob)
      expect(clicks).toHaveLength(1)
      expect(clicks[0].download).toBe('aanmelden-signup.test-BORREL.svg')
      expect(clicks[0].getAttribute('href')).toBe('blob:http://signup.test/1')
      // WebKit may still be reading the blob after the click: revoked too soon,
      // the download fails on iOS Safari.
      vi.advanceTimersByTime(39_999)
      expect(revoke).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1)
      expect(revoke).toHaveBeenCalledWith('blob:http://signup.test/1')
    } finally {
      vi.useRealTimers()
      URL.createObjectURL = createObjectURL
      URL.revokeObjectURL = revokeObjectURL
    }
  })
})

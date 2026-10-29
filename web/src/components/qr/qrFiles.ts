/**
 * A QR module matrix as files to download (B-09 SD4): a standalone SVG and a
 * PNG, both made in the browser, nothing sent anywhere (ADR 0006). The PNG is a
 * pure pixel raster first -- the part a test can decode -- and only then a
 * canvas, which writes those pixels as given: no scaling, no smoothing.
 */
export type Modules = readonly (readonly boolean[])[]

/** The matrix as an SVG document: numbers only, the link itself never enters it (AC7). */
export function svgDocument(modules: Modules): string {
  const n = modules.length
  const dark = modules.flatMap((row, y) =>
    row.flatMap((on, x) =>
      on ? [`<rect x="${x}" y="${y}" width="1" height="1" fill="#000"/>`] : [],
    ),
  )
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges">`,
    `<rect width="${n}" height="${n}" fill="#fff"/>`,
    ...dark,
    '</svg>',
  ].join('')
}

/** Each module a `k × k` block, `k = floor(max / n)`: opaque black or opaque white (AC6). */
export function qrPixels(
  modules: Modules,
  max = 1024,
): { data: Uint8ClampedArray<ArrayBuffer>; width: number; height: number } {
  const n = modules.length
  const k = Math.floor(max / n)
  const width = n * k
  // Opaque white throughout, then each dark pixel's red, green and blue to 0.
  const data = new Uint8ClampedArray(width * width * 4).fill(255)
  for (let y = 0; y < width; y++) {
    const row = modules[Math.floor(y / k)]
    for (let x = 0; x < width; x++) {
      if (row[Math.floor(x / k)]) data.fill(0, (y * width + x) * 4, (y * width + x) * 4 + 3)
    }
  }
  return { data, width, height: width }
}

export function pngBlob(modules: Modules): Promise<Blob> {
  const { data, width, height } = qrPixels(modules)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (context === null) return Promise.reject(new Error('no 2d canvas'))
  context.putImageData(new ImageData(data, width, height), 0, 0)
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob === null ? reject(new Error('no PNG')) : resolve(blob)),
      'image/png',
    )
  })
}

/**
 * Hands the browser a file through a blob URL and `<a download>`: both work over
 * plain HTTP at the venue, where the File System Access API and sharing do not (AC9).
 */
export function saveFile(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

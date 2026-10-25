/**
 * A QR token out of one camera frame (B-05 SD18, AC43), by `jsqr` (approved at
 * T12): pure JavaScript over the frame's RGBA pixels, no worker, no wasm, no
 * request. It is imported on first use, so only a page that opens the camera loads it.
 */
export interface Frame {
  data: Uint8ClampedArray
  width: number
  height: number
}

export async function decode(frame: Frame): Promise<string | null> {
  const { default: jsQR } = await import('jsqr')
  const found = jsQR(frame.data, frame.width, frame.height, { inversionAttempts: 'dontInvert' })
  return found === null || found.data === '' ? null : found.data
}

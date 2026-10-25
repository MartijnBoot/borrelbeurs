// @vitest-environment jsdom
// The camera only where the browser allows it (B-05 SD17, AC42).
import { afterEach, describe, expect, it } from 'vitest'
import { canUseCamera } from './camera'

const secure = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
const devices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')

function setContext(isSecure: boolean, mediaDevices: unknown) {
  Object.defineProperty(window, 'isSecureContext', { value: isSecure, configurable: true })
  Object.defineProperty(navigator, 'mediaDevices', { value: mediaDevices, configurable: true })
}

afterEach(() => {
  if (secure) Object.defineProperty(window, 'isSecureContext', secure)
  else delete (window as { isSecureContext?: boolean }).isSecureContext
  if (devices) Object.defineProperty(navigator, 'mediaDevices', devices)
  else delete (navigator as { mediaDevices?: unknown }).mediaDevices
})

describe('canUseCamera (AC42)', () => {
  it('is false without a secure context, as over plain HTTP at the venue', () => {
    setContext(false, { getUserMedia: () => Promise.reject(new Error('no')) })
    expect(canUseCamera()).toBe(false)
  })

  it('is false without mediaDevices', () => {
    setContext(true, undefined)
    expect(canUseCamera()).toBe(false)
  })

  it('is true with both', () => {
    setContext(true, { getUserMedia: () => Promise.reject(new Error('no')) })
    expect(canUseCamera()).toBe(true)
  })
})

// The wallet writes' Idempotency-Key (B-05 SD24; AC18, AC20).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { newIdempotencyKey } from './idempotencyKey'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('newIdempotencyKey', () => {
  it('is 32 hex characters, which the server pattern accepts', () => {
    const key = newIdempotencyKey()
    expect(key).toMatch(/^[0-9a-f]{32}$/)
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,128}$/)
  })

  it('differs every time', () => {
    const keys = new Set(Array.from({ length: 200 }, () => newIdempotencyKey()))
    expect(keys.size).toBe(200)
  })

  it('works without crypto.randomUUID, as outside a secure context (AC20)', () => {
    const { getRandomValues } = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: getRandomValues.bind(globalThis.crypto) })
    expect('randomUUID' in globalThis.crypto).toBe(false)
    expect(newIdempotencyKey()).toMatch(/^[0-9a-f]{32}$/)
  })
})

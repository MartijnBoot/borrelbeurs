/**
 * Starts the real app for the suite (PD14) through `serverProcess.ts`, and
 * hands the file it wrote -- base URL and keys, under the OS temp dir -- to
 * the tests through `E2E_SERVER`. The launcher stays up until global teardown
 * closes its stdin.
 */
import type { ChildProcess } from 'node:child_process'
import { startServer } from './serverProcess'

declare global {
  var e2eServer: ChildProcess | undefined
}

export default async function globalSetup(): Promise<void> {
  const { child, out } = await startServer('shared')
  globalThis.e2eServer = child
  process.env.E2E_SERVER = out
}

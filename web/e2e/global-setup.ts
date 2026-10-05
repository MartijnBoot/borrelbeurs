/**
 * Starts the real app for the suite (PD14): runs
 * `tests/integration/realapp/serve.py`, waits for its `ready`, and hands the
 * file it wrote -- base URL and keys, under the OS temp dir -- to the tests
 * through `E2E_SERVER`. The launcher stays up until global teardown closes
 * its stdin.
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const REPO_ROOT = resolve(import.meta.dirname, '..', '..')
const READY_TIMEOUT_MS = 120_000

declare global {
  var e2eServer: ChildProcess | undefined
}

export default async function globalSetup(): Promise<void> {
  const out = join(tmpdir(), `borrelbeurs-e2e-${process.pid}.json`)
  const child = spawn(
    'uv',
    ['run', 'python', '-m', 'tests.integration.realapp.serve', '--out', out],
    { cwd: REPO_ROOT, stdio: ['pipe', 'pipe', 'inherit'] },
  )
  globalThis.e2eServer = child

  await new Promise<void>((ready, fail) => {
    const timer = setTimeout(
      () => fail(new Error('serve.py was not ready in time')),
      READY_TIMEOUT_MS,
    )
    child.stdout!.on('data', (chunk: Buffer) => {
      if (chunk.toString().includes('ready')) {
        clearTimeout(timer)
        ready()
      }
    })
    child.once('exit', (code) => {
      clearTimeout(timer)
      fail(new Error(`serve.py exited ${code} before it was ready`))
    })
    child.once('error', (error) => {
      clearTimeout(timer)
      fail(error)
    })
  })
  process.env.E2E_SERVER = out
}

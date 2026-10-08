/**
 * Starting and stopping `tests/integration/realapp/serve.py` (PD14, Phase 6
 * PD15): global setup starts the shared server with it, and `admin.spec.ts`
 * its own `--empty` one beside it.
 *
 * `startServer` waits for the launcher's `ready` and returns it with the file
 * it wrote (base URL and keys, under the OS temp dir). `stopServer` closes its
 * stdin -- the launcher's stop, which a signal on Windows would skip -- and
 * kills it only if it has not exited within a minute.
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const REPO_ROOT = resolve(import.meta.dirname, '..', '..')
const READY_TIMEOUT_MS = 120_000

export interface ServerProcess {
  child: ChildProcess
  /** The file `serve.py` wrote: `{base_url, keys, log}`. */
  out: string
}

export async function startServer(name: string, args: string[] = []): Promise<ServerProcess> {
  const out = join(tmpdir(), `borrelbeurs-e2e-${name}-${process.pid}.json`)
  const child = spawn(
    'uv',
    ['run', 'python', '-m', 'tests.integration.realapp.serve', '--out', out, ...args],
    { cwd: REPO_ROOT, stdio: ['pipe', 'pipe', 'inherit'] },
  )

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
  return { child, out }
}

export async function stopServer(child: ChildProcess | undefined): Promise<void> {
  if (child === undefined || child.exitCode !== null) return
  const exited = new Promise<void>((done) => child.once('exit', () => done()))
  child.stdin!.end()
  const timer = setTimeout(() => child.kill(), 60_000)
  await exited
  clearTimeout(timer)
}

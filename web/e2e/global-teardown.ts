/**
 * Stops the launcher global setup started: closing its stdin makes it stop the
 * app, delete the keys file and drop the scratch database (`serve.py`). Killed
 * only if it has not exited within 60 s.
 */
import './global-setup'

export default async function globalTeardown(): Promise<void> {
  const child = globalThis.e2eServer
  if (child === undefined || child.exitCode !== null) return
  const exited = new Promise<void>((done) => child.once('exit', () => done()))
  child.stdin!.end()
  const timer = setTimeout(() => child.kill(), 60_000)
  await exited
  clearTimeout(timer)
}

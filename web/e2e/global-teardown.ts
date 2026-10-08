/**
 * Stops the launcher global setup started: closing its stdin makes it stop the
 * app, delete the keys file and drop the scratch database (`serve.py`). Killed
 * only if it has not exited within 60 s (`serverProcess.ts`).
 */
import './global-setup'
import { stopServer } from './serverProcess'

export default async function globalTeardown(): Promise<void> {
  await stopServer(globalThis.e2eServer)
}

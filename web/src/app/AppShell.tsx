/**
 * The page frame every route renders inside (SD4): v1's header -- logo,
 * title, nav (`koers.html:238-261`) -- then SD19's connection banner while
 * the WebSocket is offline, and the page itself. `headerExtra` is where a
 * page puts its own header content, as the board does with its clock.
 */
import type { ReactNode } from 'react'
import { Logo } from '../components/ui/Logo'
import { NavMenu } from '../components/ui/NavMenu'
import { selectStatus, useExchange } from '../features/exchange'
import styles from './AppShell.module.css'

export interface AppShellProps {
  routes: readonly string[]
  onLogout: () => void
  headerExtra?: ReactNode
  children: ReactNode
}

export function AppShell({ routes, onLogout, headerExtra, children }: AppShellProps) {
  const offline = useExchange(selectStatus) === 'offline'
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <Logo alt="Bier Beurs" className={styles.logo} />
          <h1>Beurs Borrel</h1>
        </div>
        {headerExtra}
        <NavMenu routes={routes} onLogout={onLogout} />
      </header>
      {offline && (
        <div className={styles.banner} role="status">
          Verbinding verbroken — opnieuw verbinden…
        </div>
      )}
      <main className={styles.main}>{children}</main>
    </div>
  )
}

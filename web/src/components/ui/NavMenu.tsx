/**
 * The header menu (SD13): exactly the `allowed_routes` it is given, in that
 * order, plus "Uitloggen". The label map is presentation only -- it decides
 * nothing about access, and a route it lacks renders as its path rather than
 * being dropped. Ported from v1's unified nav (`koers.html:246-259, 293-338`).
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import styles from './NavMenu.module.css'

const LABELS: Readonly<Record<string, string>> = {
  '/': 'Home',
  '/koers': 'Live koersbord',
  '/bar': 'Bar',
  '/manipulation': 'Spel mechanica',
  '/settings': 'Instellingen',
}

export interface NavMenuProps {
  routes: readonly string[]
  onLogout: () => void
}

export function NavMenu({ routes, onLogout }: NavMenuProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onClick = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('click', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onClick)
    }
  }, [open])

  return (
    <div className={styles.nav} ref={root}>
      <button
        type="button"
        className={styles.button}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        Menu <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className={styles.panel} role="menu">
          {routes.map((route) => (
            <Link
              key={route}
              className={styles.item}
              role="menuitem"
              to={route}
              onClick={() => setOpen(false)}
            >
              {LABELS[route] ?? route}
            </Link>
          ))}
          <div className={styles.sep} aria-hidden="true" />
          <button
            type="button"
            className={`${styles.item} ${styles.logout}`}
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onLogout()
            }}
          >
            Uitloggen
          </button>
        </div>
      )}
    </div>
  )
}

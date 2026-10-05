import styles from './pages.module.css'

/** SD13: a route not in the session's `allowed_routes` -- shown, never redirected. */
export function NoAccess() {
  return <p className={styles.notice}>Geen toegang</p>
}

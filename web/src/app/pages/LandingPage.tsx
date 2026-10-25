/**
 * The landing choice at `/` without a crew session (B-05 SD20, AC1): the
 * theme's logo, then "Speler" to `/speler` and "Crew" to `/login`. No shell,
 * no nav; with a crew session `/` is the home page, as before.
 */
import { Link } from 'react-router'
import { Logo } from '../../components/ui/Logo'
import styles from './LandingPage.module.css'

export function LandingPage() {
  return (
    <main className={styles.wrap}>
      <Logo alt="Beurs Borrel" className={styles.logo} />
      <nav className={styles.choices} aria-label="Kies">
        <Link to="/speler" className={styles.choice}>
          Speler
        </Link>
        <Link to="/login" className={styles.choice}>
          Crew
        </Link>
      </nav>
    </main>
  )
}

/**
 * The logo (Phase 6 PD9): painted from `--img-logo` -- set by `/theme.css` on
 * first paint and by `ThemeProvider` live -- with the bundled logo as the
 * fallback. The login page has no socket, so it paints from `/theme.css`
 * alone; both agree on first paint. The caller's class sets the size.
 */
import styles from './Logo.module.css'

export function Logo({ alt, className }: { alt: string; className?: string }) {
  return (
    <span
      role="img"
      aria-label={alt}
      className={className === undefined ? styles.logo : `${styles.logo} ${className}`}
    />
  )
}

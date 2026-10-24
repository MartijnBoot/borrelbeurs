/**
 * A price change's direction (B-02 SD4, SD11; PD7): the 8×8 rise or fall icon,
 * named "stijgt" or "daalt" because it stands in for the word. Nothing for an
 * unchanged price, which shows "—". The colour is the change text's (SD2).
 */
import { PixelIcon } from '../../components/ui/PixelIcon'
import type { DeltaDirection } from '../../lib/format'
import styles from './KoersPage.module.css'

export function DeltaIcon({ direction }: { direction: DeltaDirection | null }) {
  if (direction === null) return null
  return (
    <PixelIcon
      name={direction}
      label={direction === 'rise' ? 'stijgt' : 'daalt'}
      className={styles.deltaIcon}
    />
  )
}

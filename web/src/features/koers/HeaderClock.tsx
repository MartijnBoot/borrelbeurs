import { useEffect, useState } from 'react'
import { exchangeStore } from '../exchange'
import styles from './KoersPage.module.css'

const TIME = new Intl.DateTimeFormat('nl-NL', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** `HH:MM:SS` on the server's clock: `Date.now()` plus the skew offset (SD18). */
function serverTime(): string {
  return TIME.format(Date.now() + exchangeStore.getState().skewOffsetMs)
}

export function HeaderClock() {
  const [text, setText] = useState(serverTime)
  useEffect(() => {
    const timer = setInterval(() => setText(serverTime()), 500)
    return () => clearInterval(timer)
  }, [])
  return <div className={styles.clock}>{text}</div>
}

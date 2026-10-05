import type { ButtonHTMLAttributes } from 'react'
import styles from './Button.module.css'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `selected` marks the current choice in a group (the preset picker). */
  selected?: boolean
}

export function Button({ selected = false, className, type = 'button', ...rest }: ButtonProps) {
  const classes = [styles.button, selected ? styles.selected : '', className ?? '']
  return (
    <button
      type={type}
      aria-pressed={selected || undefined}
      className={classes.filter(Boolean).join(' ')}
      {...rest}
    />
  )
}

import type { ReactNode } from 'react'
import styles from './Card.module.css'

export function Card({
  children,
  padded = true,
  className = '',
}: {
  children: ReactNode
  padded?: boolean
  className?: string
}) {
  return <div className={`${styles.card} ${padded ? styles.padded : ''} ${className}`}>{children}</div>
}

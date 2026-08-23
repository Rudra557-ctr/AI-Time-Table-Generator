import type { ReactNode } from 'react'
import { Icon } from './Icon'
import styles from './Banner.module.css'

export function Banner({
  tone,
  title,
  children,
}: {
  tone: 'ok' | 'warn' | 'error'
  title: string
  children?: ReactNode
}) {
  return (
    <div className={`${styles.banner} ${styles[tone]}`}>
      <Icon name={tone === 'ok' ? 'check' : 'alert'} size={16} />
      <div>
        <div className={styles.title}>{title}</div>
        {children && <div className={styles.body}>{children}</div>}
      </div>
    </div>
  )
}

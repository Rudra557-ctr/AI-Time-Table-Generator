import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import styles from './EmptyState.module.css'

export function EmptyState({
  icon,
  title,
  description,
  action,
  tone = 'neutral',
}: {
  icon: IconName
  title: string
  description?: string
  action?: ReactNode
  tone?: 'neutral' | 'ok'
}) {
  return (
    <div className={styles.wrap}>
      <div className={`${styles.iconWrap} ${styles[tone]}`}>
        <Icon name={icon} size={22} />
      </div>
      <div className={styles.title}>{title}</div>
      {description && <div className={styles.desc}>{description}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}

import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import styles from './EmptyState.module.css'

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: IconName
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className={styles.wrap}>
      <div className={styles.iconWrap}>
        <Icon name={icon} size={22} />
      </div>
      <div className={styles.title}>{title}</div>
      {description && <div className={styles.desc}>{description}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}

import { Card } from './Card'
import { Icon, type IconName } from './Icon'
import styles from './StatCard.module.css'

export function StatCard({
  label,
  value,
  suffix,
  tone = 'neutral',
  icon,
}: {
  label: string
  value: string | number
  suffix?: string
  tone?: 'neutral' | 'ok' | 'warn' | 'error'
  icon?: IconName
}) {
  return (
    <Card className={`${styles.tintCard} ${styles[`blob-${tone}`]}`}>
      <div className={styles.head}>
        <div className={styles.label}>{label}</div>
        {icon && (
          <span className={styles.iconChip}>
            <Icon name={icon} size={14} />
          </span>
        )}
      </div>
      <div className={styles.valueRow}>
        <span className={styles.value}>{value}</span>
        {suffix && <span className={`${styles.suffix} ${styles[tone]}`}>{suffix}</span>}
      </div>
    </Card>
  )
}

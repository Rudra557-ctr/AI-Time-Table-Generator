import { Card } from './Card'
import styles from './StatCard.module.css'

export function StatCard({
  label,
  value,
  suffix,
  tone = 'neutral',
}: {
  label: string
  value: string | number
  suffix?: string
  tone?: 'neutral' | 'ok' | 'warn' | 'error'
}) {
  return (
    <Card>
      <div className={styles.label}>{label}</div>
      <div className={styles.valueRow}>
        <span className={styles.value}>{value}</span>
        {suffix && <span className={`${styles.suffix} ${styles[tone]}`}>{suffix}</span>}
      </div>
    </Card>
  )
}

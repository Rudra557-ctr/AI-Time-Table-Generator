import styles from './ProgressBar.module.css'

export function ProgressBar({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'ok' | 'warn' }) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className={styles.track}>
      <div className={`${styles.fill} ${styles[tone]}`} style={{ width: `${clamped}%` }} />
    </div>
  )
}
